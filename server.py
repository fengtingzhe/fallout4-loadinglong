#!/usr/bin/env python3
"""
Fallout 4 加载优化 MOD 文件自动检测工具 — 后端服务
====================================================
本地 Flask 服务，提供以下能力：
  - 扫描游戏根目录下的关键文件
  - 读取 Fallout4.exe 版本、F4SE 版本等
  - 抓取 F4SE / Nexus Mods 最新支持的版本
  - 返回 JSON 供前端渲染
"""

import os
import re
import json
import subprocess
import glob as glob_mod
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, send_from_directory

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

# Nexus Mods 已知 Mod ID
NEXUS_MOD_IDS = {
    "address_library": 47327,       # Address Library for F4SE Plugins
    "long_loading_fix": 73469,      # Long Loading Times Fix
}

# 已知的 Fallout 4 版本与对应 F4SE 版本映射
KNOWN_FO4_VERSIONS = {
    "1.11.221": "0.7.8",   # Next-gen update (2024) - F4SE 0.7.8
    "1.10.984": "0.7.2",   # Pre-next-gen (second latest)
    "1.10.163": "0.6.23",  # Older
    "1.10.162": "0.6.21",
    "1.10.138": "0.6.19",
    "1.10.130": "0.6.17",
    "1.10.120": "0.6.16",
    "1.10.114": "0.6.15",
    "1.10.111": "0.6.14",
    "1.10.106": "0.6.13",
    "1.10.98":  "0.6.9",
    "1.10.89":  "0.6.8",
    "1.10.82":  "0.6.6",
    "1.10.80":  "0.6.5",
    "1.10.75":  "0.6.4",
    "1.10.64":  "0.6.3",
    "1.10.50":  "0.6.2",
    "1.10.40":  "0.6.1",
    "1.10.26":  "0.6.0",
    "1.9.4":    "0.5.0",
    "1.8.7":    "0.4.2",
    "1.7.22":   "0.4.1",
    "1.7.15":   "0.3.11",
    "1.7.12":   "0.3.9",
    "1.7.9":    "0.3.7",
    "1.6.9":    "0.3.3",
    "1.5.416":  "0.2.7",
    "1.5.414":  "0.2.6",
    "1.5.307":  "0.2.5",
    "1.5.211":  "0.2.4",
    "1.5.205":  "0.2.3",
    "1.5.157":  "0.2.2",
    "1.5.151":  "0.2.1",
    "1.5.141":  "0.2.0",
    "1.4.132":  "0.1.5",
    "1.4.131":  "0.1.4",
    "1.4.124":  "0.1.3",
    "1.3.47":   "0.1.2",
    "1.3.45":   "0.1.1",
    "1.3.28":   "0.0.19",
    "1.2.37":   "0.0.16",
}

# 文件检测清单
DETECTION_LIST = [
    {
        "id": "fallout4_exe",
        "category": "游戏本体",
        "name": "Fallout4.exe",
        "relative_path": "Fallout4.exe",
        "type": "exe_version",
        "required": True,
    },
    {
        "id": "f4se_loader",
        "category": "F4SE",
        "name": "f4se_loader.exe",
        "relative_path": "f4se_loader.exe",
        "type": "exe_exists",
        "required": True,
    },
    {
        "id": "f4se_dll",
        "category": "F4SE",
        "name": "f4se_*.dll",
        "relative_path": "",  # 动态匹配
        "type": "f4se_dll",
        "required": True,
    },
    {
        "id": "f4se_steam_loader",
        "category": "F4SE",
        "name": "f4se_steam_loader.dll",
        "relative_path": "f4se_steam_loader.dll",
        "type": "file_exists",
        "required": False,
    },
    {
        "id": "address_library_bin",
        "category": "Address Library",
        "name": "version-*.bin (Address Library)",
        "relative_path": "Data\\F4SE\\Plugins\\",
        "type": "address_library",
        "required": True,
    },
    {
        "id": "address_library_dll",
        "category": "Address Library",
        "name": "version.dll (Address Library)",
        "relative_path": "Data\\F4SE\\Plugins\\version.dll",
        "type": "file_exists",
        "required": False,
    },
    {
        "id": "long_loading_dll",
        "category": "加载优化",
        "name": "Long Loading Times Fix (LongLoadingTimesFix.dll)",
        "relative_path": "Data\\F4SE\\Plugins\\LongLoadingTimesFix.dll",
        "type": "file_exists",
        "required": True,
    },
    {
        "id": "long_loading_ini",
        "category": "加载优化",
        "name": "Long Loading Times Fix (LongLoadingTimesFix.ini)",
        "relative_path": "Data\\F4SE\\Plugins\\LongLoadingTimesFix.ini",
        "type": "file_exists",
        "required": False,
    },
]

# ---------------------------------------------------------------------------
# Flask 应用
# ---------------------------------------------------------------------------

# 获取 server.py 所在目录的绝对路径（确保在任何工作目录下都能正确运行）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 工具函数 — 版本读取
# ---------------------------------------------------------------------------

def get_file_version_ps(filepath: str) -> Optional[str]:
    """
    通过 PowerShell 读取 Windows PE 文件的 FileVersion。
    返回如 "1.11.221.0" 的字符串，失败返回 None。
    """
    if not os.path.isfile(filepath):
        return None
    try:
        ps_cmd = (
            f'PowerShell -NoProfile -Command '
            f'"(Get-Item \'{filepath}\').VersionInfo.FileVersion"'
        )
        result = subprocess.run(
            ps_cmd, capture_output=True, text=True, shell=True, timeout=10
        )
        version = result.stdout.strip()
        if version:
            return version
    except Exception as exc:
        log.warning("PowerShell version read failed for %s: %s", filepath, exc)
    return None


def normalize_game_version(raw_version: str) -> str:
    """
    将 PE 文件版本号转为游戏社区常用格式。
    例如 "1.11.221.0" → "1.11.221"
    """
    if not raw_version:
        return ""
    parts = raw_version.strip().split(".")
    if len(parts) >= 3:
        return ".".join(parts[:3])
    return raw_version


# ---------------------------------------------------------------------------
# 扫描逻辑
# ---------------------------------------------------------------------------

def scan_fallout4_exe(game_path: str) -> dict:
    """检测 Fallout4.exe"""
    exe_path = os.path.join(game_path, "Fallout4.exe")
    exists = os.path.isfile(exe_path)
    raw_ver = get_file_version_ps(exe_path) if exists else None
    version = normalize_game_version(raw_ver) if raw_ver else None

    expected_f4se = KNOWN_FO4_VERSIONS.get(version or "", None)

    result = {
        "id": "fallout4_exe",
        "name": "Fallout4.exe",
        "category": "游戏本体",
        "path": exe_path,
        "exists": exists,
        "current_version": version,
        "expected_version": None,  # 游戏版本本身无"期望值"
        "status": "ok" if exists else "missing",
        "note": f"对应 F4SE 版本: {expected_f4se}" if expected_f4se else "未知版本映射",
    }

    if not exists:
        result["status"] = "missing"
        result["note"] = "⚠ 游戏主程序未找到"
    elif not version:
        result["status"] = "warning"
        result["note"] = "⚠ 无法读取版本号"
    elif version not in KNOWN_FO4_VERSIONS:
        result["status"] = "warning"
        result["note"] = f"⚠ 未知版本（已知版本: {', '.join(list(KNOWN_FO4_VERSIONS.keys())[:5])}...）"

    return result


def scan_f4se_loader(game_path: str) -> dict:
    """检测 f4se_loader.exe"""
    path = os.path.join(game_path, "f4se_loader.exe")
    exists = os.path.isfile(path)
    raw_ver = get_file_version_ps(path) if exists else None
    version = normalize_game_version(raw_ver) if raw_ver else None

    result = {
        "id": "f4se_loader",
        "name": "f4se_loader.exe",
        "category": "F4SE",
        "path": path,
        "exists": exists,
        "current_version": version,
        "expected_version": None,
        "status": "ok" if exists else "missing",
        "note": "",
    }

    if not exists:
        result["note"] = "⚠ F4SE Loader 未安装"
    elif not version:
        result["status"] = "warning"
        result["note"] = "⚠ 无法读取 F4SE 版本"

    return result


def scan_f4se_dll(game_path: str, game_version: Optional[str]) -> dict:
    """检测 f4se_*.dll（匹配游戏版本）"""
    # 匹配模式：f4se_1_11_221.dll 等
    pattern = os.path.join(game_path, "f4se_*.dll")
    matches = glob_mod.glob(pattern)

    result = {
        "id": "f4se_dll",
        "name": "f4se_*.dll",
        "category": "F4SE",
        "path": os.path.join(game_path, "f4se_*.dll"),
        "exists": len(matches) > 0,
        "current_version": None,
        "expected_version": None,
        "status": "missing",
        "note": "",
        "found_files": [],
    }

    if matches:
        result["found_files"] = [os.path.basename(m) for m in matches]
        # 从文件名提取版本：f4se_1_11_221.dll → 1.11.221
        versions_found = []
        for f in matches:
            m = re.match(r"f4se_(\d+_\d+_\d+)\.dll", os.path.basename(f), re.IGNORECASE)
            if m:
                versions_found.append(m.group(1).replace("_", "."))

        if versions_found:
            result["current_version"] = versions_found[0]

        if game_version:
            expected_dll = f"f4se_{game_version.replace('.', '_')}.dll"
            result["expected_version"] = expected_dll
            if any(expected_dll.lower() == os.path.basename(f).lower() for f in matches):
                result["status"] = "ok"
                result["note"] = f"✅ 与游戏版本 {game_version} 匹配"
            else:
                result["status"] = "mismatch"
                result["note"] = f"❌ 当前: {result['current_version']}，期望: {game_version}"
        else:
            result["status"] = "ok" if matches else "missing"
            result["note"] = "⚠ 无法确认是否匹配（游戏版本未知）"
    else:
        result["note"] = "⚠ F4SE DLL 未找到"

    return result


def scan_address_library(game_path: str, game_version: Optional[str]) -> dict:
    """检测 Address Library 文件"""
    plugins_dir = os.path.join(game_path, "Data", "F4SE", "Plugins")
    bin_pattern = os.path.join(plugins_dir, "version-*.bin")
    dll_path = os.path.join(plugins_dir, "version.dll")

    bin_files = glob_mod.glob(bin_pattern)
    dll_exists = os.path.isfile(dll_path)

    result = {
        "id": "address_library_bin",
        "name": "Address Library (.bin)",
        "category": "Address Library",
        "path": bin_pattern,
        "exists": len(bin_files) > 0,
        "current_version": None,
        "expected_version": None,
        "status": "missing",
        "note": "",
        "found_files": [],
        "version_dll_exists": dll_exists,
    }

    if bin_files:
        result["found_files"] = [os.path.basename(f) for f in bin_files]
        # 从文件名提取版本：version-1-11-221-0.bin → 1.11.221
        versions = []
        for f in bin_files:
            m = re.match(r"version-(\d+-\d+-\d+-\d+)\.bin", os.path.basename(f))
            if m:
                parts = m.group(1).split("-")
                versions.append(".".join(parts[:3]))

        if versions:
            result["current_version"] = versions[0]

        if game_version:
            expected_prefix = f"version-{game_version.replace('.', '-')}"
            result["expected_version"] = f"{expected_prefix}-*.bin"
            if any(f.startswith(expected_prefix) for f in result["found_files"]):
                result["status"] = "ok"
                result["note"] = f"✅ 与游戏版本 {game_version} 匹配"
            else:
                result["status"] = "mismatch"
                result["note"] = f"❌ 当前: {result['current_version'] or '未知'}，需要: {game_version}"
        else:
            result["status"] = "ok"
            result["note"] = "⚠ 无法确认版本匹配（游戏版本未知）"
    else:
        result["note"] = "⚠ Address Library 未安装（加载优化必需）"

    if not dll_exists:
        if result["note"]:
            result["note"] += "；version.dll 缺失"
        else:
            result["note"] = "⚠ version.dll 未找到"

    return result


def scan_generic_file(game_path: str, item: dict) -> dict:
    """通用文件存在性检测"""
    path = os.path.join(game_path, item["relative_path"])
    exists = os.path.isfile(path)

    return {
        "id": item["id"],
        "name": item["name"],
        "category": item["category"],
        "path": path,
        "exists": exists,
        "current_version": None,
        "expected_version": None,
        "status": "ok" if exists else "missing",
        "note": "" if exists else f"⚠ {item['name']} 未找到",
    }


# ---------------------------------------------------------------------------
# 远程版本抓取
# ---------------------------------------------------------------------------

def fetch_f4se_latest() -> dict:
    """
    从 https://f4se.silverlock.org/ 抓取最新 F4SE 版本信息。
    解析格式: "Fallout 4 runtime <game_version> - build: <f4se_version>"
    返回 version_mappings 字典，包含多个 game_version → f4se_version 映射。
    """
    result = {
        "source": "https://f4se.silverlock.org/",
        "version_mappings": {},       # {game_version: f4se_version, ...}
        "latest_f4se": None,
        "latest_game_version": None,
        "supported_game_versions": [],
        "success": False,
        "error": None,
    }

    try:
        resp = requests.get("https://f4se.silverlock.org/", timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text()

        # 尝试解析 "Fallout 4 runtime <version> - build: <f4se_version>" 格式
        # 匹配示例: "Fallout 4 runtime 1.11.221 - build: 0.7.8"
        runtime_pattern = re.compile(
            r'Fallout\s*4\s+runtime\s+(\d+\.\d+\.\d+)\s*[-–—]\s*build:\s*v?(\d+\.\d+\.\d+)',
            re.IGNORECASE
        )
        for m in runtime_pattern.finditer(text):
            game_ver = m.group(1)
            f4se_ver = m.group(2)
            result["version_mappings"][game_ver] = f4se_ver

        # 后备: 旧格式 "Current build: v0.7.8" + 单独的版本号列表
        if not result["version_mappings"]:
            # 提取 F4SE 构建号
            m = re.search(
                r'Current\s+(?:build|version)[:\s]+v?(\d+\.\d+\.\d+)',
                text, re.IGNORECASE
            )
            f4se_ver = m.group(1) if m else None

            # 提取所有 game 版本号
            game_versions = re.findall(r'(\d+\.\d+\.\d+)', text)
            seen = set()
            unique_game_versions = []
            for v in game_versions:
                if v not in seen and v != f4se_ver:
                    seen.add(v)
                    unique_game_versions.append(v)

            # 猜测: 最新 F4SE 对应最新 game version
            if unique_game_versions and f4se_ver:
                for gv in unique_game_versions:
                    result["version_mappings"][gv] = f4se_ver
                result["latest_f4se"] = f4se_ver
                result["latest_game_version"] = unique_game_versions[0]

        if result["version_mappings"]:
            result["success"] = True
            # 推断最新版本（第一个映射通常是最新的）
            sorted_versions = sorted(
                result["version_mappings"].keys(),
                key=lambda v: tuple(int(x) for x in v.split(".")),
                reverse=True
            )
            if sorted_versions:
                result["latest_game_version"] = sorted_versions[0]
                result["latest_f4se"] = result["version_mappings"][sorted_versions[0]]
            result["supported_game_versions"] = sorted_versions
        else:
            result["error"] = "无法解析 F4SE 版本信息（格式可能已变更）"

    except requests.RequestException as exc:
        result["error"] = f"网络请求失败: {exc}"
        log.warning("F4SE fetch failed: %s", exc)
    except Exception as exc:
        result["error"] = f"解析失败: {exc}"
        log.warning("F4SE parse failed: %s", exc)

    return result


def fetch_nexus_mod_info(mod_id: int) -> dict:
    """
    获取 Nexus Mods 上的 Mod 版本信息。
    优先使用 NEXUS_API_KEY 调用 Nexus API；
    如果没有 API Key，则抓取 Nexus HTML 页面解析 Version 字段。
    """
    result = {
        "source": f"https://www.nexusmods.com/fallout4/mods/{mod_id}",
        "mod_id": mod_id,
        "name": None,
        "version": None,
        "updated_date": None,
        "method": None,      # "api" or "html_scrape"
        "success": False,
        "error": None,
    }

    api_key = os.environ.get("NEXUS_API_KEY", "")

    # ---- 方法 1: Nexus API（需要 API Key）----
    if api_key:
        try:
            headers = {"apikey": api_key, "Accept": "application/json"}
            url = f"https://api.nexusmods.com/v1/games/fallout4/mods/{mod_id}.json"
            resp = requests.get(url, headers=headers, timeout=15)

            if resp.status_code == 200:
                data = resp.json()
                result["name"] = data.get("name")
                result["version"] = data.get("version")
                result["updated_date"] = data.get("updated_time") or data.get("updated_timestamp")
                result["method"] = "api"
                result["success"] = True
                return result
            elif resp.status_code == 401:
                log.warning("Nexus API key invalid, falling back to HTML scrape")
            elif resp.status_code == 404:
                result["error"] = f"Mod ID {mod_id} 未找到"
                return result
            else:
                log.warning("Nexus API returned HTTP %s, falling back to HTML", resp.status_code)
        except requests.RequestException as exc:
            log.warning("Nexus API request failed: %s, falling back to HTML", exc)
        except Exception as exc:
            log.warning("Nexus API parse failed: %s, falling back to HTML", exc)

    # ---- 方法 2: HTML 页面抓取（无需 API Key）----
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
        resp = requests.get(result["source"], headers=headers, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 尝试多种常见 Version 字段格式:
        # 格式 1: <dt>Version</dt><dd>1.2.0</dd>
        version_dt = soup.find("dt", string=re.compile(r"^\s*Version\s*$", re.IGNORECASE))
        if version_dt and version_dt.find_next("dd"):
            result["version"] = version_dt.find_next("dd").get_text(strip=True)

        # 格式 2: <span class="stat">Version</span> ... <span>1.2.0</span>
        if not result["version"]:
            for stat in soup.find_all(["div", "span"], class_=re.compile(r"stat", re.I)):
                text = stat.get_text(strip=True)
                m = re.match(r"Version\s*(.+)", text, re.IGNORECASE)
                if m:
                    result["version"] = m.group(1).strip()
                    break

        # 格式 3: 在 inline JSON/JS 中搜索 "version":"x.y.z"
        if not result["version"]:
            for script in soup.find_all("script"):
                if script.string:
                    m = re.search(r'"version"\s*:\s*"([^"]+)"', script.string)
                    if m:
                        result["version"] = m.group(1)
                        break

        # 格式 4: meta 标签
        if not result["version"]:
            meta = soup.find("meta", {"name": re.compile(r"version", re.I)})
            if meta and meta.get("content"):
                result["version"] = meta.get("content")

        # 格式 5: 页面标题中提取版本号，如 "Mod Name 1.2.0"
        if not result["version"]:
            title = soup.find("title")
            if title:
                title_text = title.get_text(strip=True)
                m = re.search(r'(\d+\.\d+(?:\.\d+)?)\s*(?:at|$)', title_text)
                if m:
                    result["version"] = m.group(1)

        # 格式 6: 纯文本兜底 — 用 soup.get_text("\n") 获取纯文本
        # 匹配 "Version\n1.1.2" 或 "Version  1.1.2" 等模式
        if not result["version"]:
            plain = soup.get_text("\n")
            # 在纯文本中搜索 Version 后紧跟的版本号
            m = re.search(
                r'Version\s*[\n\r\s]+\s*(\d+\.\d+(?:\.\d+)?)',
                plain, re.IGNORECASE
            )
            if m:
                result["version"] = m.group(1).strip()

        # 提取 Mod 名称
        title_tag = soup.find("title")
        if title_tag:
            name = title_tag.get_text(strip=True)
            # 清理 " at Fallout 4 Nexus" 等后缀
            name = re.sub(r'\s*(?:at|-)+\s*Fallout\s*4\s*Nexus.*$', '', name, flags=re.IGNORECASE).strip()
            result["name"] = name

        if result["version"]:
            result["method"] = "html_scrape"
            result["success"] = True
        elif not result["error"]:
            result["error"] = "HTML 页面中未找到 Version 字段（页面结构可能已变更）"

    except requests.RequestException as exc:
        if not result["error"]:
            result["error"] = f"网络请求失败: {exc}"
        log.warning("Nexus HTML fetch failed for mod %s: %s", mod_id, exc)
    except Exception as exc:
        if not result["error"]:
            result["error"] = f"解析失败: {exc}"
        log.warning("Nexus HTML parse failed for mod %s: %s", mod_id, exc)

    return result


def get_known_latest() -> dict:
    """
    返回本地维护的已知最新版本（作为在线抓取的后备参考）。
    数据需随 MOD 更新而手动维护。
    """
    return {
        "f4se": {
            "version_mappings": {
                "1.11.221": "0.7.8",
                "1.10.984": "0.7.2",
                "1.10.163": "0.6.23",
            },
            "latest_f4se": "0.7.8",
            "latest_game_version": "1.11.221",
            "source": "local",
        },
        "address_library": {
            "version": "1.11.221",  # 通常匹配最新游戏版本
            "mod_id": NEXUS_MOD_IDS["address_library"],
            "source": "local",
        },
        "long_loading_fix": {
            "version": "1.1.2",     # 请根据实际最新版本更新
            "mod_id": NEXUS_MOD_IDS["long_loading_fix"],
            "source": "local",
        },
    }


# ---------------------------------------------------------------------------
# API 路由
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """返回前端页面"""
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api/scan", methods=["GET"])
def api_scan():
    """
    扫描指定游戏路径，返回所有检测结果。

    Query params:
        path: Fallout 4 游戏根目录路径
        fetch_remote: 是否抓取远程最新版本（true/false，默认 true）
    """
    game_path = request.args.get("path", "").strip()
    fetch_remote = request.args.get("fetch_remote", "true").lower() != "false"

    if not game_path:
        return jsonify({"success": False, "error": "请提供游戏路径参数 ?path=..."}), 400

    if not os.path.isdir(game_path):
        return jsonify({"success": False, "error": f"路径不存在或不是目录: {game_path}"}), 400

    # 强制转绝对路径
    game_path = os.path.abspath(game_path)

    # ---- 本地文件扫描 ----
    results = []

    # 1. Fallout4.exe（需要先扫描以获取游戏版本）
    fo4_result = scan_fallout4_exe(game_path)
    game_version = fo4_result.get("current_version")
    results.append(fo4_result)

    # 2. f4se_loader.exe
    results.append(scan_f4se_loader(game_path))

    # 3. f4se_*.dll
    results.append(scan_f4se_dll(game_path, game_version))

    # 4. f4se_steam_loader.dll（非必需）
    steam_loader = os.path.join(game_path, "f4se_steam_loader.dll")
    results.append({
        "id": "f4se_steam_loader",
        "name": "f4se_steam_loader.dll",
        "category": "F4SE",
        "path": steam_loader,
        "exists": os.path.isfile(steam_loader),
        "current_version": None,
        "expected_version": None,
        "required": False,
        "status": "ok" if os.path.isfile(steam_loader) else "warning",
        "note": "" if os.path.isfile(steam_loader) else "⚠ 非必需文件缺失（Steam 版通常不需要）",
    })

    # 5. Address Library
    results.append(scan_address_library(game_path, game_version))

    # ---- 6. Long Loading Times Fix (LongLoadingTimesFix.dll) ----
    # 官方插件名为 LongLoadingTimesFix.dll，兼容旧命名 Long Loading Times Fix.dll
    plugins_dir = os.path.join(game_path, "Data", "F4SE", "Plugins")

    # 主检测路径（官方命名）
    llfix_dll_primary = os.path.join(plugins_dir, "LongLoadingTimesFix.dll")
    llfix_ini_primary = os.path.join(plugins_dir, "LongLoadingTimesFix.ini")
    # 兼容旧命名 fallback
    llfix_dll_fallback = os.path.join(plugins_dir, "Long Loading Times Fix.dll")
    llfix_ini_fallback = os.path.join(plugins_dir, "Long Loading Times Fix.ini")

    dll_exists = os.path.isfile(llfix_dll_primary)
    dll_fallback_exists = os.path.isfile(llfix_dll_fallback)
    ini_exists = os.path.isfile(llfix_ini_primary)
    ini_fallback_exists = os.path.isfile(llfix_ini_fallback)

    dll_path = llfix_dll_primary if dll_exists else (llfix_dll_fallback if dll_fallback_exists else llfix_dll_primary)
    ini_path = llfix_ini_primary if ini_exists else (llfix_ini_fallback if ini_fallback_exists else llfix_ini_primary)
    effective_dll_exists = dll_exists or dll_fallback_exists
    effective_ini_exists = ini_exists or ini_fallback_exists

    # ---- F4SE 日志检测 ----
    userprofile = os.environ.get("USERPROFILE", "")
    f4se_log_path = os.path.join(userprofile, "Documents", "My Games", "Fallout4", "F4SE", "f4se.log")
    llfix_own_log_path = os.path.join(userprofile, "Documents", "My Games", "Fallout4", "F4SE", "LongLoadingTimesFix.log")

    f4se_log_confirmed = False
    if os.path.isfile(f4se_log_path):
        try:
            with open(f4se_log_path, "r", encoding="utf-8", errors="ignore") as fh:
                log_content = fh.read()
            if "LongLoadingTimesFix.dll" in log_content and "loaded correctly" in log_content:
                f4se_log_confirmed = True
        except Exception:
            pass

    llfix_own_log_exists = os.path.isfile(llfix_own_log_path)

    # ---- 组装 DLL 检测结果 ----
    dll_note_parts = []
    if effective_dll_exists:
        if dll_exists:
            dll_note_parts.append("官方命名 LongLoadingTimesFix.dll")
        elif dll_fallback_exists:
            dll_note_parts.append("⚠ 使用旧命名 Long Loading Times Fix.dll，建议重命名为 LongLoadingTimesFix.dll")
    else:
        dll_note_parts.append("⚠ LongLoadingTimesFix.dll 未找到")

    if f4se_log_confirmed:
        dll_note_parts.append("✅ 已在 f4se.log 中确认插件加载成功")

    dll_status = "ok" if effective_dll_exists else "missing"
    if f4se_log_confirmed and not effective_dll_exists:
        dll_status = "warning"
        dll_note_parts.append("日志显示已加载但 DLL 文件未检测到")

    results.append({
        "id": "long_loading_dll",
        "name": "Long Loading Times Fix (LongLoadingTimesFix.dll)",
        "category": "加载优化",
        "path": dll_path,
        "exists": effective_dll_exists,
        "current_version": None,
        "expected_version": None,
        "required": True,
        "status": dll_status,
        "note": " | ".join(dll_note_parts) if dll_note_parts else "",
        "f4se_log_confirmed": f4se_log_confirmed,
        "f4se_log_path": f4se_log_path,
    })

    # ---- 组装 INI 检测结果 ----
    ini_note_parts = []
    if effective_ini_exists:
        if ini_exists:
            ini_note_parts.append("官方命名 LongLoadingTimesFix.ini")
        elif ini_fallback_exists:
            ini_note_parts.append("⚠ 使用旧命名 Long Loading Times Fix.ini，建议重命名")
        try:
            with open(ini_path, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read(500)
            if "EnableLog" in content or "LoadingScreen" in content or "FPS" in content:
                ini_note_parts.append("配置文件包含有效配置项")
        except Exception:
            pass
    else:
        ini_note_parts.append("⚠ 配置文件缺失（非必需）")

    results.append({
        "id": "long_loading_ini",
        "name": "Long Loading Times Fix (LongLoadingTimesFix.ini)",
        "category": "加载优化",
        "path": ini_path,
        "exists": effective_ini_exists,
        "current_version": None,
        "expected_version": None,
        "required": False,
        "status": "ok" if effective_ini_exists else "warning",
        "note": " | ".join(ini_note_parts) if ini_note_parts else "",
    })

    # ---- LongLoadingTimesFix.log 存在性（辅助证据） ----
    results.append({
        "id": "long_loading_log",
        "name": "LongLoadingTimesFix.log (辅助证据)",
        "category": "加载优化",
        "path": llfix_own_log_path,
        "exists": llfix_own_log_exists,
        "current_version": None,
        "expected_version": None,
        "required": False,
        "status": "ok" if llfix_own_log_exists else "warning",
        "note": "插件运行日志存在，表明插件曾成功运行" if llfix_own_log_exists else "⚠ 日志文件不存在（非必需）",
    })

    # ---- f4se.log 存在性 ----
    f4se_log_exists = os.path.isfile(f4se_log_path)
    results.append({
        "id": "f4se_log",
        "name": "f4se.log (F4SE 日志)",
        "category": "加载优化",
        "path": f4se_log_path,
        "exists": f4se_log_exists,
        "current_version": None,
        "expected_version": None,
        "required": False,
        "status": "ok" if f4se_log_exists else "warning",
        "note": (
            "F4SE 日志存在" + ("，LongLoadingTimesFix.dll 加载确认" if f4se_log_confirmed else "")
        ) if f4se_log_exists else "⚠ F4SE 日志不存在（非必需）",
        "f4se_llfix_confirmed": f4se_log_confirmed,
    })

    # ---- 远程版本抓取 ----
    remote = {}
    if fetch_remote:
        remote["f4se"] = fetch_f4se_latest()
        remote["address_library"] = fetch_nexus_mod_info(NEXUS_MOD_IDS["address_library"])
        remote["long_loading_fix"] = fetch_nexus_mod_info(NEXUS_MOD_IDS["long_loading_fix"])

    # 始终提供本地已知版本作为参考
    remote["known_latest"] = get_known_latest()

    # ---- 将远程版本注入检测结果 ----
    # F4SE 远程推荐版本（针对当前游戏版本）
    f4se_remote_data = remote.get("f4se", {})
    f4se_mappings = f4se_remote_data.get("version_mappings", {})
    f4se_remote_for_current = f4se_mappings.get(game_version) if game_version else None
    # 后备: 使用本地已知映射
    if not f4se_remote_for_current and game_version:
        f4se_remote_for_current = KNOWN_FO4_VERSIONS.get(game_version)

    addr_remote_ver = remote.get("address_library", {}).get("version")
    llfix_remote_ver = remote.get("long_loading_fix", {}).get("version")

    for r in results:
        if r["id"] in ("f4se_loader", "f4se_dll", "f4se_steam_loader"):
            r["remote_latest_version"] = f4se_remote_for_current
        elif r["id"] in ("address_library_bin", "address_library_dll"):
            r["remote_latest_version"] = addr_remote_ver or remote["known_latest"]["address_library"]["version"]
        elif r["id"] in ("long_loading_dll", "long_loading_ini", "long_loading_log", "f4se_log"):
            r["remote_latest_version"] = llfix_remote_ver or remote["known_latest"]["long_loading_fix"]["version"]
        else:
            r["remote_latest_version"] = None  # Fallout4.exe

    # ---- 整体状态摘要 ----
    missing = [r for r in results if r["status"] == "missing"]
    mismatches = [r for r in results if r["status"] == "mismatch"]
    warnings = [r for r in results if r["status"] == "warning"]

    all_ok = len(missing) == 0 and len(mismatches) == 0
    required_missing = [r for r in missing if r.get("required", True) or r["id"] in {
        "fallout4_exe", "f4se_loader", "f4se_dll", "address_library_bin", "long_loading_dll"
    }]

    if not game_version:
        summary = "⚠ 无法检测游戏版本，请确认 Fallout4.exe 存在且可读取"
    elif all_ok:
        summary = "✅ 所有加载优化相关文件检测正常，游戏可以正常加载 MOD"
    elif required_missing:
        names = ", ".join(r["name"] for r in required_missing)
        summary = f"❌ 缺少关键文件: {names}"
    elif mismatches:
        names = ", ".join(r["name"] for r in mismatches)
        summary = f"⚠ 版本不匹配: {names}"
    else:
        summary = "⚠ 存在警告项，建议检查"

    # 升级/回退建议（优先使用远程数据）
    recommendation = ""
    effective_f4se = f4se_remote_for_current or (KNOWN_FO4_VERSIONS.get(game_version) if game_version else None)

    if game_version and effective_f4se:
        f4se_dll_result = next((r for r in results if r["id"] == "f4se_dll"), None)
        if f4se_dll_result and f4se_dll_result["status"] != "ok":
            recommendation = f"建议安装/更新 F4SE 至版本 {effective_f4se}（匹配游戏版本 {game_version}）"
        else:
            recommendation = f"当前游戏版本 {game_version}，推荐 F4SE {effective_f4se}"
    elif game_version:
        recommendation = f"游戏版本 {game_version} 不在已知映射中，建议手动检查 F4SE 兼容性"

    return jsonify({
        "success": True,
        "game_path": game_path,
        "game_version": game_version,
        "scan_time": datetime.now().isoformat(),
        "results": results,
        "remote": remote,
        "summary": summary,
        "recommendation": recommendation,
        "stats": {
            "total": len(results),
            "ok": len([r for r in results if r["status"] == "ok"]),
            "missing": len(missing),
            "mismatch": len(mismatches),
            "warning": len(warnings),
        },
    })


@app.route("/api/remote", methods=["GET"])
def api_remote():
    """单独获取远程最新版本信息"""
    remote = {
        "f4se": fetch_f4se_latest(),
        "address_library": fetch_nexus_mod_info(NEXUS_MOD_IDS["address_library"]),
        "long_loading_fix": fetch_nexus_mod_info(NEXUS_MOD_IDS["long_loading_fix"]),
        "known_latest": get_known_latest(),
    }
    return jsonify({"success": True, "remote": remote})


@app.route("/api/health", methods=["GET"])
def api_health():
    """健康检查"""
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})


# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    port = 5080
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass

    # Use ASCII-safe banner (avoids encoding issues in Windows CMD)
    print("=" * 60)
    print("  Fallout 4 Loading Optimizer - Backend Server")
    print(f"  URL: http://127.0.0.1:{port}")
    print(f"  Press Ctrl+C to stop")
    print("=" * 60)

    app.run(host="127.0.0.1", port=port, debug=False)
