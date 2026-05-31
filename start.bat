@echo off
title Fallout 4 Loading Optimizer Check Tool
setlocal enabledelayedexpansion

rem ============================================================
rem  Fallout 4 Loading Times Fix Detection Tool
rem  Step 1: Check Python  Step 2: Install deps  Step 3: Start
rem ============================================================

rem Switch to script directory FIRST
cd /d "%~dp0"

rem Switch console to UTF-8 (must be before any Chinese output)
chcp 65001 > nul 2> nul

echo.
echo ================================================================
echo    Fallout 4 MOD Detection Tool
echo ================================================================
echo.

rem ============================================================
rem  Step 1: Check Python
rem ============================================================
echo [1/3] Checking Python...
python --version > nul 2> nul
if %errorlevel% neq 0 (
    echo [ERROR] Python not found!
    echo Please install Python 3.8+ and check "Add Python to PATH"
    echo Download: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo   %%i

pip --version > nul 2> nul
if %errorlevel% neq 0 (
    echo [WARN] pip not found, using python -m pip...
    set PIP_CMD=python -m pip
) else (
    set PIP_CMD=pip
)
echo   pip ready

rem ============================================================
rem  Step 2: Install dependencies
rem ============================================================
echo.
echo [2/3] Checking dependencies...

python -c "import flask, requests, bs4" 2> nul
if %errorlevel% neq 0 (
    echo   Installing dependencies (flask, requests, beautifulsoup4)...
    !PIP_CMD! install -r "requirements.txt" --no-warn-script-location
    if !errorlevel! neq 0 (
        echo.
        echo [ERROR] Dependency install failed! Check network and retry.
        echo You can also run: pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
    echo   Done!
) else (
    echo   Dependencies OK (flask, requests, beautifulsoup4)
)

rem ============================================================
rem  Step 3: Start server
rem ============================================================
set PORT=5080

echo.
echo ================================================================
echo   [3/3] Starting backend server...
echo.
echo   URL: http://127.0.0.1:%PORT%
echo.
echo   Browser will open automatically.
echo   Press Ctrl+C to stop, or close this window.
echo ================================================================
echo.

rem Open browser after 2-second delay (ping -n 3 = ~2s)
start "" cmd /c "ping 127.0.0.1 -n 3 > nul && start http://127.0.0.1:%PORT%"

rem Start Flask server (runs in foreground)
python server.py %PORT%

rem ============================================================
echo.
echo ================================================================
echo   Server stopped.
echo ================================================================
echo.
pause
