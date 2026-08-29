@echo off
chcp 65001 >nul
setlocal

set PROJECT_DIR=D:\WorkBuddy\outputs\projects\2026-08-17-14-05-54\CAD-Knowledge-Base
set PYTHON=C:\Users\hufanrong\.workbuddy\binaries\python\versions\3.13.12\python.exe

cd /d "%PROJECT_DIR%"
set PYTHONPATH=%PROJECT_DIR%
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1

echo ==========================================
echo   CAD 知识库 - 本地启动
echo   数据仅保存在本机，不上传任何云端
echo ==========================================
echo.

"%PYTHON%" start_local.py

if %errorlevel% neq 0 (
    echo.
    echo 启动过程出错，请按任意键退出 ...
    pause >nul
    exit /b %errorlevel%
)
