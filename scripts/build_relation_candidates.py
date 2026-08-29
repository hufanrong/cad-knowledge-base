# -*- coding: utf-8 -*-
"""候选关系生成器：packing_items(设备名) × texts(FTS) → relation_candidates。

背景：箱单项（跟踪表）无设备位号字段，单证号 MNN-HN 在图纸数据中不存在，
"位号↔箱单"无可靠直接键。采用弱信号候选模式：
  设备名称在图纸 texts 中命中 → 该图 equipment_tags 位号 → 候选关系（待人工确认）。
候选一律 status='pending'，不写入任何主表。

用法:
    python scripts/build_relation_candidates.py --dry-run
    python scripts/build_relation_candidates.py --yes
"""
import argparse
import re
import sqlite3
import sys
import uuid
from collections import Counter
from datetime import datetime

DB = r"D:/WorkBuddy/work/data/knowledge_base/database/cadkb.db"

DDL = """
CREATE TABLE IF NOT EXISTS relation_candidates (
    cand_id TEXT PRIMARY KEY,
    cand_type TEXT NOT NULL,
    entity_key TEXT,
    target_key TEXT,
    drawing_id TEXT,
    evidence TEXT,
    confidence REAL,
    status TEXT DEFAULT 'pending',
    source TEXT,
    created_at TEXT,
    confirmed_at TEXT,
    confirmed_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_rcand_status ON relation_candidates(status);
CREATE INDEX IF NOT EXISTS idx_rcand_target ON relation_candidates(target_key);
CREATE INDEX IF NOT EXISTS idx_rcand_entity ON relation_candidates(entity_key);
"""

# 设备名清理：去括号注释/修改标记
RE_CLEAN = re.compile(r"[（(][^）)]*[）)]|（\d+\.\d+修改）|\s+")


def norm_name(name: str) -> str:
    n = RE_CLEAN.sub("", name or "").strip()
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()

    # 设备级箱单项（跟踪表来源）
    items = cur.execute(
        "SELECT packing_no, equip_name, vendor, source_file_id FROM packing_items").fetchall()
    # 唯一设备名 → FTS 查 texts 命中的 drawing_id
    names = {}
    for pno, ename, vendor, fid in items:
        n = norm_name(ename)
        if len(n) >= 2:
            names.setdefault(n, []).append((pno, ename, vendor, fid))
    print(f"箱单项 {len(items)} 条 | 唯一设备名 {len(names)} 个")

    # FTS 查询每个设备名命中的图纸
    name_drawings = {}
    for n in names:
        try:
            rows = cur.execute(
                "SELECT DISTINCT t.drawing_id FROM texts_fts f JOIN texts t ON t.rowid = f.rowid "
                "WHERE texts_fts MATCH ? LIMIT 20", (f'"{n}"',)).fetchall()
            ds = [r[0] for r in rows]
        except Exception:
            ds = []
        if ds:
            name_drawings[n] = ds
    print(f"FTS 命中文图纸的设备名 {len(name_drawings)} 个")

    # 生成候选：设备名命中图纸 → 该图 equipment_tags 位号
    cands = []
    for n, dss in name_drawings.items():
        for did in dss:
            tags = cur.execute(
                "SELECT DISTINCT tag_no FROM equipment_tags WHERE drawing_id=? AND tag_type='equipment' LIMIT 30",
                (did,)).fetchall()
            for (tag,) in tags:
                for pno, ename, vendor, fid in names[n][:3]:   # 每设备名最多取3条箱单项
                    cands.append({
                        "cand_type": "equipment_packing",
                        "entity_key": tag,
                        "target_key": pno,
                        "drawing_id": did,
                        "evidence": f"设备名[{ename}]在该图texts命中; 厂家[{vendor}]",
                        "confidence": 0.45,
                    })

    print(f"生成候选 {len(cands)} 条（pending，待人工确认）")
    if args.dry_run:
        print("\n== 验收点 JH2408270005 的候选 ==")
        hit = [c for c in cands if c["target_key"] == "JH2408270005"]
        print(f"候选数: {len(hit)}")
        for c in hit[:8]:
            print(f"   {c['entity_key']:<14} conf={c['confidence']} | {c['evidence'][:50]}")
        print("\n== 候选箱单分布 TOP10 ==")
        for k, v in Counter(c["target_key"] for c in cands).most_common(10):
            print(f"   {k}: {v}")
        con.close()
        return

    if not args.yes:
        ans = input(f"即将写入 relation_candidates {len(cands)} 条。确认？[y/N]: ")
        if ans.strip().lower() not in ("y", "yes"):
            print("已取消。")
            con.close()
            return

    wcon = sqlite3.connect(DB)
    wcon.execute("PRAGMA busy_timeout=60000")
    for stmt in DDL.strip().split(";"):
        s = stmt.strip()
        if s:
            wcon.execute(s)
    wcon.execute("DELETE FROM relation_candidates WHERE cand_type='equipment_packing'")
    now = datetime.now().isoformat(" ")
    for c in cands:
        wcon.execute(
            "INSERT INTO relation_candidates (cand_id, cand_type, entity_key, target_key, drawing_id, evidence, confidence, status, source, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), c["cand_type"], c["entity_key"], c["target_key"],
             c["drawing_id"], c["evidence"], c["confidence"], "pending", "name_fts", now))
    wcon.commit()
    n = wcon.execute("SELECT COUNT(*) FROM relation_candidates").fetchone()[0]
    print(f"已写入 relation_candidates {n} 条")
    wcon.close()
    con.close()


if __name__ == "__main__":
    main()
