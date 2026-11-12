# -*- coding: utf-8 -*-
"""migrate_manono_exclusive.py — 共享资料库 → 马诺诺项目专属迁移。

范围（老板指令 2026-08-30）：
  1. files 表 project_id 为 空/NULL 的 1097 份 → 'manono'
  2. 向量库 87,204 个 project_id='' chunks 的 metadata → 'manono'
  3. 迁移前备份 cadkb.db + VectorDB 到 _archive/db_backups/

用法：python scripts/migrate_manono_exclusive.py [--no-backup]
"""
from __future__ import annotations

import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import sqlalchemy
from sqlalchemy import text

from src.database.connection import get_session
from src.index.vector_index import VectorIndex

KB = Path(r"D:\WorkBuddy\work\data\knowledge_base")
DB_FILE = KB / "database" / "cadkb.db"
VDB_DIR = KB / "VectorDB"
BACKUP_ROOT = Path(r"D:\WorkBuddy\_archive\db_backups")
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP_DIR = BACKUP_ROOT / f"2026-08-30_共享库转manono专属_{STAMP}"
BATCH = 3000


def backup() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[1/4] 备份数据库 -> {BACKUP_DIR}")
    t0 = time.time()
    dst_db = BACKUP_DIR / "cadkb.db"
    shutil.copy2(DB_FILE, dst_db)
    print(f"      cadkb.db 已备份 ({dst_db.stat().st_size/1024/1024:.0f} MB, {time.time()-t0:.0f}s)")
    t0 = time.time()
    dst_vdb = BACKUP_DIR / "VectorDB"
    shutil.copytree(VDB_DIR, dst_vdb, dirs_exist_ok=True)
    print(f"      VectorDB 已备份 ({time.time()-t0:.0f}s)")


def migrate_files() -> int:
    print("[2/4] 更新 files 表 project_id ...")
    s = get_session()
    try:
        res = s.execute(
            text("UPDATE files SET project_id='manono' "
                 "WHERE project_id IS NULL OR project_id=''")
        )
        s.commit()
        return res.rowcount or 0
    finally:
        s.close()


def migrate_vector() -> int:
    print("[3/4] 更新向量库 chunks project_id='' -> 'manono' ...")
    vi = VectorIndex()
    vi.count()
    col = vi._collection
    done = 0
    offset = 0
    while True:
        r = col.get(where={"project_id": ""}, limit=BATCH, offset=offset,
                    include=["metadatas"])
        ids = r.get("ids", [])
        metas = r.get("metadatas", [])
        if not ids:
            break
        new_metas = []
        for m in metas:
            m = dict(m or {})
            m["project_id"] = "manono"
            new_metas.append(m)
        col.update(ids=ids, metadatas=new_metas)
        done += len(ids)
        print(f"      已更新 {done} / 87204 chunks (批次 {offset})", flush=True)
        if len(ids) < BATCH:
            break
        offset += BATCH
    return done


def verify() -> None:
    print("[4/4] 验证 ...")
    s = get_session()
    try:
        rows = s.execute(
            text("SELECT project_id, COUNT(*) FROM files GROUP BY project_id")
        ).fetchall()
        print("      files 分布: " + ", ".join(f"{r[0] or '(空)'}={r[1]}" for r in rows))
        man = s.execute(
            text("SELECT COUNT(*) FROM files WHERE project_id='manono'")
        ).scalar()
        plat = s.execute(
            text("SELECT COUNT(*) FROM files WHERE project_id IS NULL OR project_id=''")
        ).scalar()
        print(f"      manono={man} | 平台级={plat}")
    finally:
        s.close()

    vi = VectorIndex()
    vi.count()
    col = vi._collection
    plat_chunks = 0
    offset = 0
    while True:
        r = col.get(where={"project_id": ""}, limit=BATCH, offset=offset,
                    include=["metadatas"])
        ids = r.get("ids", [])
        plat_chunks += len(ids)
        if len(ids) < BATCH:
            break
        offset += BATCH
    print(f"      向量库: 剩余 project_id='' chunks = {plat_chunks}（应为 0）")
    print(f"      向量库总数 = {col.count()}")


def main() -> int:
    no_backup = "--no-backup" in sys.argv
    if not no_backup:
        backup()
    n1 = migrate_files()
    print(f"      files 已更新 {n1} 份")
    n2 = migrate_vector()
    print(f"      向量 chunks 已更新 {n2} 个")
    verify()
    print("\n迁移完成 ✅  回退: 从 %s 恢复 cadkb.db + VectorDB" % BACKUP_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
