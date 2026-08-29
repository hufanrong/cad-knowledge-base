@echo off
rem 前台启动资料库入口监听（调试用，窗口可见）
rem 后台自启由启动文件夹的「资料库入口监听.vbs」负责
rem 监听目录可用环境变量 CADKB_ENTRY_DIR 覆盖（每工程独立入口），例如：
rem   set CADKB_ENTRY_DIR=D:\WorkBuddy\Projects\PRJ-2026-002_新工程\00_入口
rem 库根/数据库路径可用 CADKB_KB_ROOT、CADKB_DB_PATH 覆盖（每工程独立子库）
cd /d D:\WorkBuddy\outputs\projects\2026-08-17-14-05-54\CAD-Knowledge-Base
C:\Users\hufanrong\.workbuddy\binaries\python\versions\3.13.12\python.exe scripts\watch_entry.py
pause
