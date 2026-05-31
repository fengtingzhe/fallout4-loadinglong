@echo off
cd /d "%~dp0"
chcp 65001 > nul 2> nul

echo ================================================================
echo   Fallout 4 Loading Optimizer Check Tool
echo ================================================================
echo.

echo [1/3] Checking Python...
python --version > nul 2> nul
if %errorlevel% neq 0 (
    echo ERROR: Python not found! Install Python 3.8+
    pause
    exit /b 1
)
echo   Python OK

echo [2/3] Checking dependencies...
python -c "import flask,requests,bs4" 2> nul
if %errorlevel% neq 0 (
    echo   Installing dependencies...
    pip install -r "%~dp0requirements.txt"
    if %errorlevel% neq 0 (
        echo ERROR: Install failed! Check network.
        pause
        exit /b 1
    )
)
echo   Dependencies OK

echo.
echo ================================================================
echo   [3/3] Starting server...
echo.
echo   URL: http://127.0.0.1:5080
echo   Press Ctrl+C to stop the server
echo ================================================================
echo.

start http://127.0.0.1:5080
python server.py 5080
pause
