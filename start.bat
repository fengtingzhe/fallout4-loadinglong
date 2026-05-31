@echo off
title Fallout 4 加载优化 MOD 检测工具
setlocal enabledelayedexpansion

:: ============================================================
::  Fallout 4 Loading Times Fix Detection Tool — 启动脚本
::  功能: 安装依赖 → 启动后端 → 打开浏览器
:: ============================================================

:: 第一步：切换到脚本所在目录
cd /d "%~dp0"

:: 设置控制台编码为 UTF-8 (65001)
chcp 65001 >nul 2>nul

echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║   Fallout 4 加载优化 MOD 检测工具                        ║
echo ╚══════════════════════════════════════════════════════════╝
echo.

:: ============================================================
:: 检查 Python
:: ============================================================
echo [1/3] 检查 Python 环境...
python --version >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python！
    echo.
    echo 请安装 Python 3.8+ 并确保勾选 "Add Python to PATH"。
    echo 下载地址: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

:: 显示 Python 版本
for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo   %%i

:: 检查 pip
pip --version >nul 2>nul
if %errorlevel% neq 0 (
    echo [警告] pip 未找到，尝试使用 python -m pip...
    set PIP_CMD=python -m pip
) else (
    set PIP_CMD=pip
)
echo   pip 已就绪

:: ============================================================
:: 安装依赖
:: ============================================================
echo.
echo [2/3] 检查 Python 依赖包...

:: 先尝试 import flask 看是否已安装
python -c "import flask, requests, bs4" 2>nul
if %errorlevel% neq 0 (
    echo   正在安装依赖 (flask, requests, beautifulsoup4)...
    !PIP_CMD! install -r "requirements.txt" --no-warn-script-location
    if !errorlevel! neq 0 (
        echo.
        echo [错误] 依赖安装失败！请检查网络连接后重试。
        echo 也可以手动执行: pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
    echo   依赖安装完成！
) else (
    echo   依赖已就绪 (flask, requests, beautifulsoup4)
)

:: ============================================================
:: 启动服务
:: ============================================================
set PORT=5080

echo.
echo ════════════════════════════════════════════════════════════
echo   [3/3] 启动后端服务...
echo.
echo   地址: http://127.0.0.1:%PORT%
echo.
echo   浏览器将自动打开。如未打开，请手动访问上述地址。
echo   按 Ctrl+C 停止服务，或直接关闭此窗口。
echo ════════════════════════════════════════════════════════════
echo.

:: 启动浏览器（异步，延迟 2 秒等待服务器就绪）
:: ping -n 3 发送 3 个包，间隔约 2 秒，用作跨版本兼容的延迟
start "" cmd /c "ping 127.0.0.1 -n 3 > nul && start http://127.0.0.1:%PORT%"

:: 启动 Flask 后端（前台运行，按 Ctrl+C 停止）
python server.py %PORT%

:: ============================================================
:: 服务结束
:: ============================================================
echo.
echo ════════════════════════════════════════════════════════════
echo   服务已停止。
echo ════════════════════════════════════════════════════════════
echo.
pause
