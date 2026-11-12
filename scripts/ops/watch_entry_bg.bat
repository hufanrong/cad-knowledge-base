@echo off
rem 资料库入口监听后台启动器（pythonw 静默退出问题 2026-11-02，改用 python.exe 最小化窗口运行）
cd /d "D:\WorkBuddy\outputs\projects\2026-08-17-14-05-54\CAD-Knowledge-Base"
"C:\Users\hufanrong\.workbuddy\binaries\python\versions\3.13.12.old.11896\python.exe" scripts\watch_entry.py >> logs\watch_run.log 2>&1
