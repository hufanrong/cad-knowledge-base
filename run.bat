@echo off
REM CAD Knowledge Base - Windows Startup Script
REM Usage: run.bat [command] [args]

cd /d "%~dp0"

if "%1"=="" (
    echo Usage: run.bat [command] [args]
    echo.
    echo Commands:
    echo   import ^<file^>      Import a CAD file
    echo   inspect ^<file^>     Inspect a file
    echo   search ^<query^>     Full-text search
    echo   status              Show system status
    echo   test                Run unit tests
    echo.
    goto :eof
)

if "%1"=="test" (
    python -m pytest tests/ -v
    goto :eof
)

python -m src.cli.main %*
