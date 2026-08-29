# -*- coding: utf-8 -*-
"""批量处理 _压缩包重试 目录中的 zip（解压并导入）。"""
import sys
from pathlib import Path
sys.path.insert(0, r"D:\WorkBuddy\outputs\projects\2026-08-17-14-05-54\CAD-Knowledge-Base")
from scripts.watch_entry import extract_and_import, _move_file

RETRY = Path(r"D:/Users/hufanrong/Desktop/资料库入口/_压缩包重试")
DONE = Path(r"D:/Users/hufanrong/Desktop/资料库入口/_已处理/20260822")
FAILED = Path(r"D:/Users/hufanrong/Desktop/资料库入口/_失败/20260822")

zips = sorted([p for p in RETRY.glob("*.zip")])
print(f"待处理 zip: {len(zips)}", flush=True)
for i, zp in enumerate(zips, 1):
    print(f"[{i}/{len(zips)}] 处理 {zp.name}", flush=True)
    try:
        r = extract_and_import(zp, FAILED)
        print(f"  结果: {r.get('status')} {r.get('message')}", flush=True)
        _move_file(zp, DONE)
    except Exception as e:
        print(f"  异常: {e}", flush=True)
        _move_file(zp, FAILED)
print("全部处理完成", flush=True)
