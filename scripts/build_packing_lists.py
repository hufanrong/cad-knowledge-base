# -*- coding: utf-8 -*-
"""箱单结构化：从 document_contents 提取箱单/设备/厂家 → packing_lists/packing_items。

数据源：document_contents 中含 JH 计划单号的 markdown 表格行
（到货跟踪表为主，列序：序号|设备名称|子项|数量|厂家|计划单号|订单号|单证号）。
幂等：以 source='doc_tracking' 定向清理重插。

用法:
    python scripts/build_packing_lists.py --dry-run
    python scripts/build_packing_lists.py --yes
"""
import argparse
import re
import sqlite3
import sys
import uuid
from collections import Counter
from datetime import datetime

DB = r"D:/WorkBuddy/work/data/knowledge_base/database/cadkb.db"

RE_JH = re.compile(r"JH\d{10}(/\d{3}(-\d{3})?|/\d{3}~\d{3})?")
RE_ORDER = re.compile(r"\b(85\d{8})\b")
RE_DOCNO = re.compile(r"\b(MNN-[A-Z]{2}-\d+[a-z]?)\b")

DDL = """
CREATE TABLE IF NOT EXISTS packing_lists (
    pack_id TEXT PRIMARY KEY,
    packing_no TEXT NOT NULL,
    order_no TEXT,
    doc_no TEXT,
    item_count INTEGER DEFAULT 0,
    source_file_id TEXT,
    source TEXT,
    created_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pack_no_src ON packing_lists(packing_no, source_file_id);
CREATE TABLE IF NOT EXISTS packing_items (
    item_id TEXT PRIMARY KEY,
    pack_id TEXT,
    packing_no TEXT NOT NULL,
    equip_name TEXT,
    vendor TEXT,
    qty TEXT,
    raw_line TEXT,
    confidence REAL,
    source_file_id TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_pitems_pack ON packing_items(pack_id);
CREATE INDEX IF NOT EXISTS idx_pitems_no ON packing_items(packing_no);
CREATE INDEX IF NOT EXISTS idx_pitems_vendor ON packing_items(vendor);
"""


def parse_line(line: str):
    """解析 markdown 表格行，返回 dict 或 None。"""
    if "|" not in line or not RE_JH.search(line):
        return None
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    jh_m = RE_JH.search(line)
    packing_no = jh_m.group(0)
    # 计划单号所在列索引 → 推断其他列（厂家在其左1、数量左2、设备名左3）
    jh_idx = next((i for i, c in enumerate(cells) if RE_JH.search(c)), None)
    if jh_idx is None:
        return None
    vendor = cells[jh_idx - 1] if jh_idx >= 1 else ""
    qty = cells[jh_idx - 2] if jh_idx >= 2 else ""
    equip_name = cells[jh_idx - 3] if jh_idx >= 3 else ""
    # 设备名若为空（区域合并行），向左找最近非空
    if not equip_name and jh_idx >= 3:
        for i in range(jh_idx - 3, -1, -1):
            if cells[i]:
                equip_name = cells[i]
                break
    order_m = RE_ORDER.search(line)
    doc_m = RE_DOCNO.search(line)
    # 过滤汇总行（设备名为空且厂家为空）
    if not equip_name and not vendor:
        return None
    return {
        "packing_no": packing_no.split("/")[0],      # 主单号（不含分段）
        "packing_no_full": packing_no,                # 含 /001-003 分段
        "equip_name": equip_name[:80],
        "vendor": vendor[:60],
        "qty": qty[:20],
        "order_no": order_m.group(1) if order_m else "",
        "doc_no": doc_m.group(1) if doc_m else "",
        "raw_line": line.strip()[:400],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute("SELECT file_id, title, content FROM document_contents").fetchall()
    con.close()

    items = []          # (file_id, parsed)
    stats = Counter()
    for fid, title, content in rows:
        if not content:
            continue
        for line in content.split("\n"):
            p = parse_line(line)
            if p:
                p["source_file_id"] = fid
                p["source_title"] = title or ""
                items.append(p)
                stats["items"] += 1

    uniq_pack = {(p["packing_no"], p["source_file_id"]) for p in items}
    print(f"解析设备行 {stats['items']} 条 | 箱单(按来源去重) {len(uniq_pack)} 个 | 唯一箱单号 {len({p['packing_no'] for p in items})} 个")

    if args.dry_run:
        print("\n== 箱单号 TOP15 ==")
        for no, cnt in Counter(p["packing_no"] for p in items).most_common(15):
            print(f"   {no}: {cnt} 行")
        print("\n== 样本 5 条 ==")
        for p in items[:5]:
            print(f"   [{p['packing_no']}] {p['equip_name'][:24]} | {p['vendor'][:16]} | {p['qty']} | {p['source_title'][:24]}")
        # 验收点：JH2408270005
        hit = [p for p in items if p["packing_no"] == "JH2408270005"]
        print(f"\n== 验收点 JH2408270005: {len(hit)} 行 ==")
        for p in hit[:3]:
            print(f"   {p['equip_name']} | {p['vendor']} | 订单 {p['order_no']} | 单证 {p['doc_no']}")
        return

    if not args.yes:
        ans = input(f"即将写入 packing_lists/packing_items。确认？[y/N]: ")
        if ans.strip().lower() not in ("y", "yes"):
            print("已取消。")
            return

    con = sqlite3.connect(DB)
    con.execute("PRAGMA busy_timeout=60000")
    for stmt in DDL.strip().split(";"):
        s = stmt.strip()
        if s:
            con.execute(s)
    con.execute("DELETE FROM packing_items")
    con.execute("DELETE FROM packing_lists")

    now = datetime.now().isoformat(" ")
    pack_ids = {}
    for (pno, fid) in uniq_pack:
        pid = str(uuid.uuid4())
        pack_ids[(pno, fid)] = pid
        group = [p for p in items if p["packing_no"] == pno and p["source_file_id"] == fid]
        g0 = group[0]
        con.execute(
            "INSERT INTO packing_lists (pack_id, packing_no, order_no, doc_no, item_count, source_file_id, source, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (pid, pno, g0["order_no"], g0["doc_no"], len(group), fid, "doc_tracking", now))
    for p in items:
        pid = pack_ids[(p["packing_no"], p["source_file_id"])]
        con.execute(
            "INSERT INTO packing_items (item_id, pack_id, packing_no, equip_name, vendor, qty, raw_line, confidence, source_file_id, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), pid, p["packing_no"], p["equip_name"], p["vendor"],
             p["qty"], p["raw_line"], 0.85, p["source_file_id"], now))
    con.commit()
    n1 = con.execute("SELECT COUNT(*) FROM packing_lists").fetchone()[0]
    n2 = con.execute("SELECT COUNT(*) FROM packing_items").fetchone()[0]
    print(f"已写入 packing_lists {n1} / packing_items {n2}")
    con.close()


if __name__ == "__main__":
    main()
