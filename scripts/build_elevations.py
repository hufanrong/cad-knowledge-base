# -*- coding: utf-8 -*-
"""标高抽取器：texts/title_block_fields → elevations 表（含 verified 校核列）。

抽取规则（基于 2026-08-23 探查）：
- %%P 是 AutoCAD 的 ± 编码，先替换
- 车间基准标高："本车间标高±0.000相当于绝对标高644.00m" → datum=644.00, datum_type='absolute'
- 直接标高文字："标高：EL.+0.800"、"顶标高10.700" → 图内局部标高（datum_type='local'）
优先级：图签(title_block_fields) > texts；一图一条主记录（datum_elevation 取绝对标高基准）。
幂等：source='rule_regex' 定向清理重插。

用法:
    python scripts/build_elevations.py --dry-run
    python scripts/build_elevations.py --yes
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
CREATE TABLE IF NOT EXISTS elevations (
    elevation_id TEXT PRIMARY KEY,
    drawing_id TEXT NOT NULL,
    datum_elevation REAL,
    datum_type TEXT,
    raw_text TEXT,
    confidence REAL,
    verified INTEGER DEFAULT 0,
    verified_by TEXT,
    verified_at TEXT,
    source TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_elev_drawing ON elevations(drawing_id);
CREATE INDEX IF NOT EXISTS idx_elev_verified ON elevations(verified);
"""

# 车间基准：绝对标高
RE_ABS = re.compile(r"绝对标高\s*([0-9]+\.?[0-9]*)")
# ±0.000 相当于（配合绝对标高使用，确认真基准行）
RE_DATUM_LINE = re.compile(r"相当于绝对标高")
# 局部标高：标高:EL.+x / 顶标高x / 板顶标高x
RE_LOCAL = re.compile(r"(?:标高[:：]?\s*(?:EL\.?\s*)?|顶标高|板顶标高)\s*([+-]?[0-9]+\.?[0-9]*)")


def clean(t: str) -> str:
    return (t or "").replace("%%P", "±").replace("%%p", "±").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()

    # 1) 图签优先：title_block_fields 中含"绝对标高"的 value
    tb = cur.execute(
        "SELECT t.drawing_id, t.value FROM title_block_fields t WHERE t.value LIKE '%绝对标高%'").fetchall()
    abs_map = {}   # drawing_id -> (datum, raw)
    for did, val in tb:
        v = clean(val)
        m = RE_ABS.search(v)
        if m:
            abs_map[did] = (float(m.group(1)), v[:200], 0.9, "title_block")

    # 2) texts 扫描：基准行（含"相当于绝对标高"）
    last_id = 0
    local_map = {}   # drawing_id -> list[(value, raw)]
    while True:
        rows = cur.execute(
            "SELECT drawing_id, text_content, rowid FROM texts WHERE rowid > ? AND text_content LIKE '%标高%' ORDER BY rowid LIMIT 50000",
            (last_id,)).fetchall()
        if not rows:
            break
        for did, tc, rid in rows:
            v = clean(tc)
            if RE_DATUM_LINE.search(v):
                m = RE_ABS.search(v)
                if m and did not in abs_map:
                    abs_map[did] = (float(m.group(1)), v[:200], 0.8, "texts")
            else:
                m = RE_LOCAL.search(v)
                if m:
                    local_map.setdefault(did, []).append((float(m.group(1)), v[:120]))
        last_id = rows[-1][2]

    con.close()

    # 汇总：一图一条主记录（绝对标高优先；无绝对标高则记局部标高集合的摘要）
    records = []
    all_dids = set(abs_map) | set(local_map)
    for did in all_dids:
        if did in abs_map:
            datum, raw, conf, src = abs_map[did]
            records.append({"drawing_id": did, "datum_elevation": datum,
                            "datum_type": "absolute", "raw_text": raw,
                            "confidence": conf, "source": "rule_regex"})
        else:
            vals = local_map[did]
            nums = sorted({v for v, _ in vals})
            raw = f"局部标高 {len(vals)} 处，范围 {nums[0]}~{nums[-1]}；例: {vals[0][1]}"
            records.append({"drawing_id": did, "datum_elevation": None,
                            "datum_type": "local_only", "raw_text": raw[:200],
                            "confidence": 0.5, "source": "rule_regex"})

    n_abs = sum(1 for r in records if r["datum_type"] == "absolute")
    print(f"标高记录 {len(records)} 张图 | 绝对标高基准 {n_abs} | 仅局部标高 {len(records)-n_abs}")
    total = 515
    print(f"覆盖率 {len(records)/total*100:.1f}% (目标 ≥60%)")

    if args.dry_run:
        print("\n== 绝对标高值分布 ==")
        for v, c in Counter(r["datum_elevation"] for r in records if r["datum_type"] == "absolute").most_common():
            print(f"   {v}: {c} 张")
        print("\n== 样本 ==")
        for r in records[:5]:
            print(f"   [{r['datum_type']}] {r['datum_elevation']} | {r['raw_text'][:70]}")
        return

    if not args.yes:
        ans = input(f"即将写入 elevations {len(records)} 条。确认？[y/N]: ")
        if ans.strip().lower() not in ("y", "yes"):
            print("已取消。")
            return

    con = sqlite3.connect(DB)
    con.execute("PRAGMA busy_timeout=60000")
    for stmt in DDL.strip().split(";"):
        s = stmt.strip()
        if s:
            con.execute(s)
    con.execute("DELETE FROM elevations WHERE source='rule_regex'")
    now = datetime.now().isoformat(" ")
    for r in records:
        con.execute(
            "INSERT INTO elevations (elevation_id, drawing_id, datum_elevation, datum_type, raw_text, confidence, verified, source, created_at) "
            "VALUES (?,?,?,?,?,?,0,?,?)",
            (str(uuid.uuid4()), r["drawing_id"], r["datum_elevation"], r["datum_type"],
             r["raw_text"], r["confidence"], r["source"], now))
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM elevations").fetchone()[0]
    print(f"已写入 elevations {n} 条（verified=0 待校核）")
    con.close()


if __name__ == "__main__":
    main()
