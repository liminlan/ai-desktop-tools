@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AI Hub Desktop

if not exist ".venv\Scripts\pythonw.exe" goto setup

start "" ".venv\Scripts\pythonw.exe" "desktop.py"
exit /b 0

:setup
echo ============================================
echo   First run: preparing desktop shell ...
echo   (needs internet, takes 1-3 minutes)
echo ============================================
echo.
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m venv .venv
) else (
    python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
    echo [!] Could not create the Python environment.
    echo     Install Python 3 from https://www.python.org/downloads/
    echo     and tick "Add python.exe to PATH", then run this again.
    echo.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install pywebview pystray pillow
if %errorlevel% neq 0 (
    echo.
    echo [!] Installing dependencies failed. Check your network and retry.
    pause
    exit /b 1
)
echo.
echo Done. Starting ...
start "" ".venv\Scripts\pythonw.exe" "desktop.py"
exit /b 0
