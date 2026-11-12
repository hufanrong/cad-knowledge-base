# -*- coding: utf-8 -*-
"""
backfill_vector_project_id.py — 向量元数据补 project_id（多项目管理平台 P1-5）
=============================================================================
背景：cadkb_chunks collection 共 ~12.4 万条向量，元数据缺 project_id，
      无法在向量检索层做工程隔离。本脚本从 cadkb.db 的 files 表建映射，
      按 drawing_id（CAD 块 / document 块均存放在该字段）批量 update
      元数据（只加字段，不重算 embedding，不删任何现有字段）。

映射规则（与 migrate_project_tags.py 一致）：
  - CAD 块（source_type != document）：drawing_id -> files.drawing_id -> project_id
  - document 块（source_type == document）：drawing_id(=file_id) -> files.file_id -> project_id
  - files.project_id 为 NULL/空 -> 平台级 ""（不归属任何工程）
  - 未命中映射 -> 保留缺省（不入库，避免误标）

用法：
  python scripts/backfill_vector_project_id.py          # dry-run 统计
  python scripts/backfill_vector_project_id.py --apply  # 写库
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

CADKB = Path(r"D:/WorkBuddy/outputs/projects/2026-08-17-14-05-54/CAD-Knowledge-Base")
KB_DB = Path(r"D:/WorkBuddy/work/data/knowledge_base/database/cadkb.db")

sys.path.insert(0, str(CADKB))
from src.core.config import get_config  # noqa: E402

BATCH = 5000


def build_maps() -> tuple[dict, dict]:
    """返回 (drawing_id->project_id, file_id->project_id)。"""
    db = sqlite3.connect(str(KB_DB))
    try:
        c = db.cursor()
        m_drawing = dict(c.execute(
            "SELECT drawing_id, project_id FROM files "
            "WHERE drawing_id IS NOT NULL AND drawing_id != ''"
        ).fetchall())
        m_file = dict(c.execute(
            "SELECT file_id, project_id FROM files"
        ).fetchall())
    finally:
        db.close()
    return m_drawing, m_file


def _norm(pid) -> str:
    return (pid or "").strip()


def scan(apply: bool = False) -> dict:
    import chromadb

    cfg = get_config()
    client = chromadb.PersistentClient(path=str(cfg.embeddings_dir))
    col = client.get_collection("cadkb_chunks")
    m_drawing, m_file = build_maps()

    total = col.count()
    n_hit = n_platform = n_project = n_miss = 0
    offset = 0
    while offset < total:
        got = col.get(offset=offset, limit=BATCH)
        ids = got["ids"]
        metas = got["metadatas"]
        new_metas: list[dict] = []
        for m in metas:
            mm = dict(m or {})
            did = (mm.get("drawing_id") or "").strip()
            is_doc = mm.get("source_type") == "document"
            pid = _norm(m_file.get(did) if is_doc else m_drawing.get(did))
            if pid:
                mm["project_id"] = pid
                n_project += 1
                n_hit += 1
            elif did:
                # 命中文件但 project_id 为空 -> 平台级
                mm["project_id"] = ""
                n_platform += 1
                n_hit += 1
            else:
                n_miss += 1
            new_metas.append(mm)
        if apply and ids and new_metas:
            col.update(ids=ids, metadatas=new_metas)
        offset += BATCH
        print(f"  进度 {offset}/{total} (命中 {n_hit})", flush=True)

    return {
        "total": total,
        "hit": n_hit,
        "platform": n_platform,
        "project": n_project,
        "miss": n_miss,
        "apply": apply,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="向量元数据补 project_id")
    parser.add_argument("--apply", action="store_true",
                        help="写库（默认 dry-run 只统计）")
    args = parser.parse_args()

    print(f"数据库: {KB_DB}")
    print(f"向量库: {get_config().embeddings_dir}")
    r = scan(apply=args.apply)
    print("=" * 50)
    print(f"总计 {r['total']} 条，可标 {r['hit']}，"
          f"其中工程级 {r['project']} / 平台级 {r['platform']}，未命中 {r['miss']}")
    print("已写库" if r["apply"] else "dry-run（未写库，加 --apply 生效）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
