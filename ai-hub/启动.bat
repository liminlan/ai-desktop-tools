@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AI Hub
cls
echo ============================================
echo   AI Hub  -  starting local service ...
echo ============================================
echo.
where python >nul 2>nul
if %errorlevel%==0 (
    python server.py
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        py -3 server.py
    ) else (
        echo [!] Python 3 not found.
        echo     Install from https://www.python.org/downloads/
        echo     and tick "Add python.exe to PATH".
        echo.
        pause
        exit /b 1
    )
)
if %errorlevel% neq 0 (
    echo.
    echo [!] service stopped with an error. see message above.
    pause
)
