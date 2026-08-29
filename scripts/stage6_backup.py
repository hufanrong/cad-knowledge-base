"""阶段6开工前数据库备份（使用 sqlite 在线备份，避免大文件拷贝中断）。"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

SRC = Path("D:/WorkBuddy/work/data/knowledge_base/database/cadkb.db")
OUT_DIR = Path("D:/WorkBuddy/work/data/knowledge_base/Temp")


def backup():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = OUT_DIR / f"cadkb_backup_{ts}_pre_stage6.db"
    dst.parent.mkdir(parents=True, exist_ok=True)

    src = sqlite3.connect(str(SRC))
    dst_conn = sqlite3.connect(str(dst))
    with dst_conn:
        src.backup(dst_conn, pages=100, progress=progress)
    dst_conn.close()
    src.close()

    # 快速校验
    conn = sqlite3.connect(str(dst))
    n = conn.execute("SELECT COUNT(*) FROM drawings").fetchone()[0]
    conn.close()
    print(f"备份完成: {dst} | drawings={n}")


def progress(status, remaining, total):
    pct = (total - remaining) / total * 100
    if remaining % 50 == 0 or remaining == 0:
        print(f"  备份进度: {pct:.1f}%", flush=True)


if __name__ == "__main__":
    backup()
