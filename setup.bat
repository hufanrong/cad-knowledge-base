@echo off
REM ============================================================
REM  CAD Knowledge Base - One-click setup (Windows)
REM  Creates venv, installs CPU torch + requirements, copies .env
REM ============================================================
setlocal
cd /d "%~dp0"

echo [1/3] Creating virtual environment...
python -m venv venv
if errorlevel 1 goto :error

call venv\Scripts\activate.bat

echo [2/3] Upgrading pip and installing dependencies (first run ~3GB, please wait)...
python -m pip install --upgrade pip
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto :error
python -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo [3/3] Creating .env from template...
if not exist .env copy .env.example .env >nul

echo.
echo ============================================================
echo  Installation complete!
echo  Activate environment : venv\Scripts\activate.bat
echo  Check status        : python -m src.cli.main status
echo  Launch GUI          : python -m src.cli.main gui
echo  Launch REST API     : python -m src.cli.main serve
echo  Edit .env for DB/ODA/LLM settings
echo ============================================================
pause
exit /b 0

:error
echo.
echo [ERROR] Setup failed. Please check the messages above.
pause
exit /b 1
