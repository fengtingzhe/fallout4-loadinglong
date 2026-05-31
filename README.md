# Fallout 4 加载优化 MOD 检测工具

自动检测 Fallout 4 根目录下加载优化相关文件的完整性、版本匹配性，并抓取远程最新支持版本进行对比。

## 功能概览

| 检测项 | 说明 |
|--------|------|
| `Fallout4.exe` | 读取游戏版本号（如 1.11.191 / 1.11.221） |
| `f4se_loader.exe` | 检测 F4SE 加载器 |
| `f4se_*.dll` | 检测 F4SE DLL 版本是否匹配游戏版本 |
| `version-*.bin` | 检测 Address Library 版本文件 |
| `Long Loading Times Fix.dll` | 检测加载优化 MOD |
| `Long Loading Times Fix.ini` | 检测加载优化配置文件 |

## 快速开始

### 1. 双击 `start.bat`

脚本会自动：
- 检查 Python 环境
- 安装依赖（flask, requests, beautifulsoup4）
- 启动本地后端服务（端口 5080）
- 打开浏览器访问检测页面

### 2. 手动启动

```bash
pip install -r requirements.txt
python server.py          # 默认端口 5080
python server.py 8080     # 自定义端口
```

然后访问 http://127.0.0.1:5080

### 3. 使用

1. 输入或粘贴 Fallout 4 游戏根目录路径
2. 点击「开始检测」
3. 查看文件状态、版本对比、远程最新版本参考

## 项目结构

```
fallout4-loadinglong/
├── start.bat              # Windows 一键启动脚本
├── requirements.txt       # Python 依赖
├── server.py              # Flask 后端服务
├── static/
│   └── index.html         # 前端 UI
└── README.md
```

## API 接口

| 端点 | 参数 | 说明 |
|------|------|------|
| `GET /api/scan` | `?path=<游戏路径>&fetch_remote=true` | 扫描文件并返回结果 |
| `GET /api/remote` | — | 获取远程最新版本信息 |
| `GET /api/health` | — | 健康检查 |

### 扫描结果 JSON 结构

```json
{
  "success": true,
  "game_path": "D:\\Steam\\steamapps\\common\\Fallout 4",
  "game_version": "1.11.221",
  "results": [
    {
      "id": "fallout4_exe",
      "name": "Fallout4.exe",
      "category": "游戏本体",
      "exists": true,
      "current_version": "1.11.221",
      "status": "ok",
      "note": "对应 F4SE 版本: 0.7.2"
    }
  ],
  "summary": "✅ 所有加载优化相关文件检测正常",
  "recommendation": "当前游戏版本 1.11.221，推荐 F4SE 0.7.2",
  "stats": { "total": 8, "ok": 7, "missing": 0, "mismatch": 0, "warning": 1 }
}
```

### 状态说明

| 状态 | 含义 |
|------|------|
| `ok` | ✅ 文件存在且版本正确 |
| `missing` | ❌ 文件缺失 |
| `mismatch` | ⚠ 版本不匹配 |
| `warning` | ⚠ 存在但无法确认版本 |

## 远程版本源

- **F4SE**: 从 https://f4se.silverlock.org/ 抓取最新版本
- **Address Library**: Nexus Mods API (#47327)，需配置 `NEXUS_API_KEY` 环境变量
- **Long Loading Times Fix**: Nexus Mods API (#62985)，需配置 `NEXUS_API_KEY`

如未配置 Nexus API Key，将使用本地维护的已知版本作为参考。

## 技术栈

- **后端**: Python 3.8+ / Flask
- **前端**: 原生 HTML/CSS/JS（无框架依赖）
- **版本读取**: PowerShell（Windows PE 文件版本）
- **远程抓取**: requests + BeautifulSoup4

## 限制

- 仅检测加载优化相关文件，不检测其他 MOD
- 所有操作在本地进行，不修改游戏文件
- 需要 Windows 环境（依赖 PowerShell 读取 PE 版本）
