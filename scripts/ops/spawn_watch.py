# -*- coding: utf-8 -*-
"""一次性派生器：由 Bash 会话启动，把 watch_entry.py 以脱离作业对象的方式拉起。

背景（2026-11-02）：WorkBuddy PowerShell 会话环境块损坏（环境变量大小写重复键），
Start-Process 派生的任何子进程均静默退出；Bash 会话环境正常，但其作业对象会在
会话结束时回收子进程，故用 CREATE_BREAKAWAY_FROM_JOB 让监听进程逃逸。

用法：python.exe spawn_watch.py   （成功打印 PID 后立即退出）
"""
import subprocess
import sys
from pathlib import Path

PROJ = Path(r"D:\WorkBuddy\outputs\projects\2026-08-17-14-05-54\CAD-Knowledge-Base")
PYW = Path(r"C:\Users\hufanrong\.workbuddy\binaries\python\versions\3.13.12.old.11896\pythonw.exe")
SCRIPT = PROJ / "scripts" / "watch_entry.py"

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

p = subprocess.Popen(
    [str(PYW), str(SCRIPT)],
    cwd=str(PROJ),
    creationflags=flags,
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
print(f"spawned PID={p.pid} breakaway=1")
