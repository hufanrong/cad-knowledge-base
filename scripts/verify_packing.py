# -*- coding: utf-8 -*-
"""装箱/箱号映射 验收核查（只读，不改数据）

用法: python scripts/verify_packing.py
      python scripts/verify_packing.py --lookup 2#
"""
import argparse
import sqlite3
import sys

DB = r"D:/WorkBuddy/work/data/knowledge_base/database/cadkb.db"


def q(con, sql, args=()):
    cur = con.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return cols, [dict(zip(cols, r)) for r in cur.fetchall()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookup", help="按箱号反查：2# / 9-2 / 7-7")
    args = ap.parse_args()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    if args.lookup:
        k = args.lookup
        rows = con.execute(
            "SELECT box_no, box_name, vendor, source_type, length_m, width_m, height_m, "
            "net_weight_kg, gross_weight_kg, item_count, substr(source_path,-52) sp "
            "FROM packing_boxes WHERE box_no=? ORDER BY vendor, source_type", (k,)).fetchall()
        print(f"\n== 箱号 {k} 命中 {len(rows)} 条（注意：厂家箱号按供应商各自编号，"
              f"同一箱号在不同厂家是不同箱，须带供应商看）==")
        by_v = {}
        for r in rows:
            by_v.setdefault(r["vendor"] or "(未识别厂商)", []).append(r)
        for v, rs in by_v.items():
            print(f"\n  ▣ {v}  —— {len(rs)} 条")
            for r in rs:
                print(f"     [{r['source_type']:<14}] {str(r['box_name'])[:22]:<22} "
                      f"{r['length_m']}×{r['width_m']}×{r['height_m']} "
                      f"净{r['net_weight_kg']} 毛{r['gross_weight_kg']} 项{r['item_count']}")
                print(f"        {r['sp']}")
        try:
            al = con.execute(
                "SELECT vendor, factory_box_no, doc_box_no, match_method, score, verified, remark "
                "FROM packing_box_aliases WHERE factory_box_no=? OR doc_box_no=? "
                "ORDER BY vendor, verified DESC", (k, k)).fetchall()
        except sqlite3.OperationalError:
            al = []
        if al:
            print(f"\n== 映射 {len(al)} 条 ==")
            for a in al:
                print(f"  {'✔已确认' if a['verified'] else '○待确认'} [{a['vendor'] or '-'}] "
                      f"厂家{a['factory_box_no']} ⇄ 单证{a['doc_box_no']}  "
                      f"{a['match_method']} {a['score']}")
                print(f"      {a['remark'][:110]}")
        return

    print("=" * 68)
    print("① 装箱数据总览")
    print("=" * 68)
    cols, rows = q(con, """
        SELECT source_type, COUNT(*) boxes, SUM(item_count) items,
               SUM(CASE WHEN confidence>=0.9 THEN 1 ELSE 0 END) 高置信
        FROM packing_boxes GROUP BY source_type ORDER BY boxes DESC""")
    print(f"  {'来源类型':<16}{'箱数':>7}{'箱内项':>8}{'高置信':>8}")
    for r in rows:
        print(f"  {r['source_type']:<16}{r['boxes']:>7}{r['items'] or 0:>8}{r['高置信']:>8}")
    tot = q(con, "SELECT COUNT(*) n, SUM(item_count) i FROM packing_boxes")[1][0]
    print(f"  {'合计':<16}{tot['n']:>7}{tot['i'] or 0:>8}")

    print("\n" + "=" * 68)
    print("② OCR 原文留痕")
    print("=" * 68)
    cols, rows = q(con, """
        SELECT COUNT(*) pages, COUNT(DISTINCT source_file_id) files,
               ROUND(AVG(mean_conf),3) avg_conf, SUM(char_count) chars
        FROM packing_ocr_raw""")
    r = rows[0]
    print(f"  OCR 页 {r['pages']} | 文件 {r['files']} | 平均置信 {r['avg_conf']} | 字符 {r['chars']}")

    print("\n" + "=" * 68)
    print("③ 验收点A：石灰乳制备 320单证 9 箱（厂家1#~8# ↔ 单证9-1~9-9）")
    print("=" * 68)
    rows = con.execute(
        "SELECT box_no, box_name, length_m, width_m, height_m, net_weight_kg, "
        "gross_weight_kg, source_type FROM packing_boxes "
        "WHERE vendor LIKE '%荥阳%' AND box_no LIKE '9-%' ORDER BY box_no").fetchall()
    if not rows:
        print("  ✗ 未命中")
    for r in rows:
        print(f"  {r['box_no']:<5} {str(r['box_name'])[:14]:<14} "
              f"{r['length_m']}×{r['width_m']}×{r['height_m']} "
              f"净{r['net_weight_kg']} 毛{r['gross_weight_kg']} [{r['source_type']}]")

    print("\n" + "=" * 68)
    print("④ 验收点B：大一重工斗提机扫描件 OCR 箱号（NE15 应为 7-1~7-7）")
    print("=" * 68)
    rows = con.execute(
        "SELECT box_no, source_type, substr(source_path,-40) sp FROM packing_boxes "
        "WHERE source_type='pdf_ocr' AND vendor LIKE '%大一%' ORDER BY sp, box_no").fetchall()
    if not rows:
        print("  ✗ 未命中")
    for r in rows:
        print(f"  {r['box_no']:<7} {r['sp']}")

    print("\n" + "=" * 68)
    print("⑤ 箱号映射表（packing_box_aliases）")
    print("=" * 68)
    try:
        cols, rows = q(con, """SELECT match_method, COUNT(*) n, SUM(verified) v
                               FROM packing_box_aliases GROUP BY match_method""")
        if not rows:
            print("  (空) 先运行 scripts/build_box_aliases.py --yes")
        for r in rows:
            print(f"  {r['match_method']:<12}{r['n']:>5} 条  已确认 {r['v'] or 0}")
        print("\n  已人工确认明细：")
        for a in con.execute(
                "SELECT vendor, factory_box_no, doc_box_no, remark FROM packing_box_aliases "
                "WHERE verified=1 ORDER BY factory_box_no"):
            print(f"    ✔ {a['vendor'][:12]:<12} 厂家{a['factory_box_no']:<4} ⇄ 单证{a['doc_box_no']:<5}"
                  f" {a['remark'][:64]}")
    except sqlite3.OperationalError as e:
        print("  ✗ 映射表不存在:", e)
    con.close()


if __name__ == "__main__":
    main()
