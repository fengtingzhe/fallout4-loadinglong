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

# Nexus Mods 已知 Mod ID（可在此处更新）
NEXUS_MOD_IDS = {
    "address_library": 47327,       # Address Library for F4SE Plugins
    "long_loading_fix": 62985,      # Long Loading Times Fix (请核实)
}

# 已知的 Fallout 4 版本与对应 F4SE 版本映射
KNOWN_FO4_VERSIONS = {
    "1.11.221": "0.7.2",   # Next-gen update (2024)
    "1.11.191": "0.6.23",  # Pre-next-gen
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
        "name": "Long Loading Times Fix.dll",
        "relative_path": "Data\\F4SE\\Plugins\\Long Loading Times Fix.dll",
        "type": "file_exists",
        "required": True,
    },
    {
        "id": "long_loading_ini",
        "category": "加载优化",
        "name": "Long Loading Times Fix.ini",
        "relative_path": "Data\\F4SE\\Plugins\\Long Loading Times Fix.ini",
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
    """
    result = {
        "source": "https://f4se.silverlock.org/",
        "f4se_version": None,
        "supported_game_versions": [],
        "success": False,
        "error": None,
    }

    try:
        resp = requests.get("https://f4se.silverlock.org/", timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text()

        # 提取 F4SE 版本号，如 "Current build: v0.7.2"
        m = re.search(r"Current\s+(?:build|version)[:\s]+v?(\d+\.\d+\.\d+)", text, re.IGNORECASE)
        if m:
            result["f4se_version"] = m.group(1)

        # 提取支持的游戏版本，如 "1.11.221", "1.11.191"
        game_versions = re.findall(r"(\d+\.\d+\.\d+)", text)
        # 去重并过滤 F4SE 自身版本
        seen = set()
        unique_versions = []
        for v in game_versions:
            if v not in seen and v != result.get("f4se_version", ""):
                seen.add(v)
                unique_versions.append(v)
        result["supported_game_versions"] = unique_versions

        if result["f4se_version"]:
            result["success"] = True
        else:
            result["error"] = "无法解析 F4SE 版本信息"

    except requests.RequestException as exc:
        result["error"] = f"网络请求失败: {exc}"
        log.warning("F4SE fetch failed: %s", exc)
    except Exception as exc:
        result["error"] = f"解析失败: {exc}"
        log.warning("F4SE parse failed: %s", exc)

    return result


def fetch_nexus_mod_info(mod_id: int) -> dict:
    """
    尝试通过 Nexus Mods API 获取 Mod 信息。
    需要用户在环境变量 NEXUS_API_KEY 中设置 API Key（可选）。
    如果无 API Key，返回基础信息。
    """
    result = {
        "source": f"https://www.nexusmods.com/fallout4/mods/{mod_id}",
        "mod_id": mod_id,
        "name": None,
        "version": None,
        "updated_date": None,
        "success": False,
        "error": None,
    }

    api_key = os.environ.get("NEXUS_API_KEY", "")
    if not api_key:
        result["error"] = "未配置 NEXUS_API_KEY（可选，将使用本地已知版本）"
        return result

    try:
        headers = {"apikey": api_key, "Accept": "application/json"}
        url = f"https://api.nexusmods.com/v1/games/fallout4/mods/{mod_id}.json"
        resp = requests.get(url, headers=headers, timeout=15)

        if resp.status_code == 200:
            data = resp.json()
            result["name"] = data.get("name")
            result["version"] = data.get("version")
            result["updated_date"] = data.get("updated_time") or data.get("updated_timestamp")
            result["success"] = True
        elif resp.status_code == 401:
            result["error"] = "API Key 无效"
        elif resp.status_code == 404:
            result["error"] = f"Mod ID {mod_id} 未找到"
        else:
            result["error"] = f"HTTP {resp.status_code}"

    except requests.RequestException as exc:
        result["error"] = f"网络请求失败: {exc}"
        log.warning("Nexus API fetch failed for mod %s: %s", mod_id, exc)
    except Exception as exc:
        result["error"] = f"解析失败: {exc}"

    return result


def get_known_latest() -> dict:
    """
    返回已知的最新版本信息（本地维护，作为在线抓取的后备）。
    这些数据需要随 MOD 更新而手动维护。
    """
    return {
        "f4se": {
            "version": "0.7.2",
            "supported_game_versions": ["1.11.221", "1.11.191"],
            "source": "local",
        },
        "address_library": {
            "version": "1.11.221",  # 通常匹配最新游戏版本
            "mod_id": NEXUS_MOD_IDS["address_library"],
            "source": "local",
        },
        "long_loading_fix": {
            "version": "1.2.0",  # 请根据实际情况更新
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

    # 4. f4se_steam_loader.dll
    steam_loader = os.path.join(game_path, "f4se_steam_loader.dll")
    results.append({
        "id": "f4se_steam_loader",
        "name": "f4se_steam_loader.dll",
        "category": "F4SE",
        "path": steam_loader,
        "exists": os.path.isfile(steam_loader),
        "current_version": None,
        "expected_version": None,
        "status": "ok" if os.path.isfile(steam_loader) else "missing",
        "note": "" if os.path.isfile(steam_loader) else "⚠ 非必需文件缺失",
    })

    # 5. Address Library
    results.append(scan_address_library(game_path, game_version))

    # 6. Long Loading Times Fix
    results.append(scan_generic_file(game_path, {
        "id": "long_loading_dll",
        "name": "Long Loading Times Fix.dll",
        "category": "加载优化",
        "relative_path": "Data\\F4SE\\Plugins\\Long Loading Times Fix.dll",
    }))

    # 7. Long Loading Times Fix.ini
    ini_path = os.path.join(game_path, "Data", "F4SE", "Plugins", "Long Loading Times Fix.ini")
    ini_exists = os.path.isfile(ini_path)
    ini_note = ""
    if ini_exists:
        # 尝试读取 ini 中的版本或说明
        try:
            with open(ini_path, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read(500)
            # 简单检查是否有关键配置项
            if "EnableLog" in content or "LoadingScreen" in content or "FPS" in content:
                ini_note = "ini 配置文件存在且包含配置项"
            else:
                ini_note = "ini 文件存在"
        except Exception:
            ini_note = "ini 存在但无法读取"
    results.append({
        "id": "long_loading_ini",
        "name": "Long Loading Times Fix.ini",
        "category": "加载优化",
        "path": ini_path,
        "exists": ini_exists,
        "current_version": None,
        "expected_version": None,
        "status": "ok" if ini_exists else "warning",
        "note": ini_note if ini_exists else "⚠ 配置文件缺失（非必需）",
    })

    # ---- 远程版本抓取 ----
    remote = {}
    if fetch_remote:
        remote["f4se"] = fetch_f4se_latest()
        remote["address_library"] = fetch_nexus_mod_info(NEXUS_MOD_IDS["address_library"])
        remote["long_loading_fix"] = fetch_nexus_mod_info(NEXUS_MOD_IDS["long_loading_fix"])

    # 始终提供本地已知版本作为参考
    remote["known_latest"] = get_known_latest()

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

    # 升级/回退建议
    recommendation = ""
    if game_version and game_version in KNOWN_FO4_VERSIONS:
        recommended_f4se = KNOWN_FO4_VERSIONS[game_version]
        # 检查当前 F4SE DLL 版本
        f4se_dll_result = next((r for r in results if r["id"] == "f4se_dll"), None)
        if f4se_dll_result and f4se_dll_result["status"] != "ok":
            recommendation = f"建议安装/更新 F4SE 至版本 {recommended_f4se}（匹配游戏版本 {game_version}）"
        elif not recommendation:
            recommendation = f"当前游戏版本 {game_version}，推荐 F4SE {recommended_f4se}"
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
