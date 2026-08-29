@echo off
chcp 65001 >nul
echo 正在关闭 CAD 知识库服务 ...

for /f "tokens=2" %%a in ('tasklist ^| findstr python.exe') do (
    echo   关闭 Python 进程 PID=%%a
    taskkill /PID %%a /F >nul 2>&1
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8501') do (
    taskkill /PID %%a /F >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000') do (
    taskkill /PID %%a /F >nul 2>&1
)

echo 服务已关闭。
pause
