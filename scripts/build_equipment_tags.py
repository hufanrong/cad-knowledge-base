# -*- coding: utf-8 -*-
"""equipment_tags 位号标注抽取入库脚本（幂等）。

从 texts 表整串匹配位号/管道编号 → equipment_tags 表。
用法:
    python scripts/build_equipment_tags.py --dry-run   # 只统计不写库
    python scripts/build_equipment_tags.py --yes       # 正式写入
"""
import argparse
import json
import re
import sqlite3
import sys
import uuid
from datetime import datetime

DB = r"D:/WorkBuddy/work/data/knowledge_base/database/cadkb.db"

# 设备位号: FC0203ME01（2字母+4数字子系统+2字母+2数字+可选字母后缀）
RE_EQUIP = re.compile(r"^[A-Z]{2}\d{4}[A-Z]{2}\d{2}[A-Z]?$")
# 管道编号: P01-PP-01AC1（P+2数字-2字母-2数字+后缀）
RE_PIPE = re.compile(r"^P\d{2}-[A-Z]{2}-\d{2}[A-Z0-9/]*$")
# 位号内子系统编号（第3-6位数字）
RE_SUBSYS = re.compile(r"^[A-Z]{2}(\d{4})")

DDL = """
CREATE TABLE IF NOT EXISTS equipment_tags (
    tag_id VARCHAR PRIMARY KEY,
    drawing_id VARCHAR NOT NULL,
    tag_no VARCHAR NOT NULL,
    tag_type VARCHAR DEFAULT 'equipment',
    x FLOAT,
    y FLOAT,
    height FLOAT,
    layer VARCHAR,
    text_id VARCHAR,
    subsystem_no VARCHAR,
    source VARCHAR DEFAULT 'text_regex',
    created_at DATETIME
);
CREATE INDEX IF NOT EXISTS idx_equiptags_drawing ON equipment_tags(drawing_id);
CREATE INDEX IF NOT EXISTS idx_equiptags_no ON equipment_tags(tag_no);
CREATE INDEX IF NOT EXISTS idx_equiptags_subsys ON equipment_tags(subsystem_no);
"""


def scan_tags(con):
    """扫描 texts 表，返回位号记录列表。"""
    cur = con.cursor()
    out = []
    last_id = 0
    while True:
        rows = cur.execute(
            "SELECT rowid, text_id, drawing_id, text_content, position, height, layer "
            "FROM texts WHERE rowid > ? ORDER BY rowid LIMIT 50000",
            (last_id,)).fetchall()
        if not rows:
            break
        for rid, tid, did, tc, pos, h, layer in rows:
            tc = (tc or "").strip()
            tag_type = None
            if RE_EQUIP.match(tc):
                tag_type = "equipment"
            elif RE_PIPE.match(tc):
                tag_type = "pipeline"
            if not tag_type:
                continue
            try:
                p = json.loads(pos)
                x, y = float(p[0]), float(p[1])
            except Exception:
                continue
            m = RE_SUBSYS.match(tc)
            out.append({
                "tag_id": str(uuid.uuid4()),
                "drawing_id": did,
                "tag_no": tc,
                "tag_type": tag_type,
                "x": x, "y": y,
                "height": h or 0.0,
                "layer": layer,
                "text_id": tid,
                "subsystem_no": m.group(1) if m else None,
            })
        last_id = rows[-1][0]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro" if args.dry_run else DB, uri=args.dry_run)
    con.execute("PRAGMA busy_timeout=60000")

    tags = scan_tags(con)
    uniq = {t["tag_no"] for t in tags}
    drawings = {t["drawing_id"] for t in tags}
    print(f"抽取位号标注 {len(tags)} 条 | 唯一位号 {len(uniq)} | 图纸 {len(drawings)} 张")

    if args.dry_run:
        from collections import Counter
        c = Counter(t["subsystem_no"] for t in tags)
        print("子系统分布 TOP15:", c.most_common(15))
        c2 = Counter(t["tag_type"] for t in tags)
        print("类型分布:", dict(c2))
        con.close()
        return

    if not args.yes:
        ans = input(f"即将写入 {len(tags)} 条到 equipment_tags（先清 source='text_regex' 旧数据）。确认？[y/N]: ")
        if ans.strip().lower() not in ("y", "yes"):
            print("已取消。")
            con.close()
            return

    for stmt in DDL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            con.execute(stmt)
    con.execute("DELETE FROM equipment_tags WHERE source='text_regex'")
    con.executemany(
        "INSERT INTO equipment_tags (tag_id, drawing_id, tag_no, tag_type, x, y, height, layer, text_id, subsystem_no, source, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(t["tag_id"], t["drawing_id"], t["tag_no"], t["tag_type"], t["x"], t["y"],
          t["height"], t["layer"], t["text_id"], t["subsystem_no"], "text_regex",
          datetime.now().isoformat(" ")) for t in tags])
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM equipment_tags").fetchone()[0]
    print(f"已写入，equipment_tags 当前 {n} 行")
    con.close()


if __name__ == "__main__":
    main()
