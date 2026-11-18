@echo off
chcp 65001 >nul
title 豆包截图挂件
set "LOCAL_PY=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"

if exist "%LOCAL_PY%" (
    start "" "%LOCAL_PY%" "%~dp0doubao_orb.py"
    exit /b
)

where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0doubao_orb.py"
    exit /b
)

echo.
echo  没找到 Python 环境。
echo  最简单的办法：直接双击「豆包截图挂件.exe」，那个不需要 Python。
echo  想用源码方式运行：装 python.org 的 Python 3.10+，并执行 pip install pillow
echo.
pause
