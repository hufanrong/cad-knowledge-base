# -*- coding: utf-8 -*-
"""厂家箱号 ↔ 物流单证箱号 映射表（packing_box_aliases）

解决的问题：同一台设备、同一只箱子，在不同资料里有两套编号
  - 厂家装箱清单：1# 2# 3# …
  - 物流单证 / 重尺表：9-1 9-2 9-3 …（单证号-箱序号）
现场按箱收货、查箱内物品时两套编号极易混淆。

映射来源（按可信度从高到低）：
  1. manual    人工确认（脚本内 SEED，附证据）
  2. dims      同厂商、跨编号体系，按 长宽高 + 名称 相似度匹配（唯一最优才采纳）
  3. sequential 扫描件文件名给出厂家箱号区间(N#~M#)，OCR 给出单证箱号 P-1~P-M，
               按升序对应 k ↔ P-k。方法可靠但方向依赖约定，verified=0 待确认

红线：
  - 不猜测。达不到阈值一律不写，进「待确认」清单
  - 一对多 / 多对一 冲突不自动定案，只报告
  - 已人工确认的记录不被自动匹配覆盖

用法:
    python scripts/build_box_aliases.py --dry-run
    python scripts/build_box_aliases.py --yes
    python scripts/build_box_aliases.py --lookup "2#"
    python scripts/build_box_aliases.py --yes --xlsx D:/tmp/箱号映射表.xlsx
"""
import argparse
import difflib
import os
import re
import sqlite3
import uuid
from collections import Counter, defaultdict
from datetime import datetime

DB = r"D:/WorkBuddy/work/data/knowledge_base/database/cadkb.db"

DDL = """
CREATE TABLE IF NOT EXISTS packing_box_aliases (
    alias_id       TEXT PRIMARY KEY,
    vendor         TEXT,
    factory_box_no TEXT,              -- 厂家箱号，如 2#
    doc_box_no     TEXT,              -- 物流单证箱号，如 9-2
    factory_box_id TEXT,              -- packing_boxes.box_id（厂家清单那条）
    doc_box_id     TEXT,              -- packing_boxes.box_id（单证/重尺表那条）
    factory_file_id TEXT,
    doc_file_id    TEXT,
    match_method   TEXT,              -- manual / dims / sequential
    score          REAL,
    verified       INTEGER DEFAULT 0, -- 1=已人工确认
    remark         TEXT,
    created_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_alias_vendor ON packing_box_aliases(vendor);
CREATE INDEX IF NOT EXISTS idx_alias_fno    ON packing_box_aliases(factory_box_no);
CREATE INDEX IF NOT EXISTS idx_alias_dno    ON packing_box_aliases(doc_box_no);
"""

# ── 人工确认种子（逐条有证据，勿凭印象增删）─────────────────────────────
SEED = [
    ("荥阳矿机石灰乳", "1#", "9-1",
     "2445磨机 7.76×3.215×3.3 ↔ 溢流球磨机 7.76×3.22×3.3，名称+尺寸双证"),
    ("荥阳矿机石灰乳", "2#", "9-2",
     "衬板 6.1×2.8×2.0 两源完全一致；本箱含泵5台（旋流器给料泵2+石灰乳输送渣浆泵2+潜水泵1）"),
    ("荥阳矿机石灰乳", "3#", "9-3",
     "大护罩 5.75×2.72×2.2 与重尺表 9-3 5.75×2.74×2.2 一致；"
     "注意：320单证 9-3 记为「球磨机大齿轮 4.3×2.0×2.15」，与重尺表冲突，待厂家澄清"),
    ("荥阳矿机石灰乳", "4#", "9-4",
     "1#胶带输送机 8.06×2.4×2.12 两源一致"),
    ("荥阳矿机石灰乳", "5#", "9-5",
     "高压启动柜 6.66×1.93×2.54 ↔ 控制柜等 6.66×1.93×2.54 完全一致；泵配件1箱在此箱"),
    ("荥阳矿机石灰乳", "6#", "9-6",
     "3米搅拌桶 3.2×3.2×3.2 两源一致"),
    ("荥阳矿机石灰乳", "7#", "9-7",
     "中转槽 2.52×2.08×2.61 两源一致"),
    ("荥阳矿机石灰乳", "8#", "9-9",
     "减速机（磨机主减速机 1.32×1.1×1.255）↔ 9-9 减速机 1.0×1.2×1.0，名称一致尺寸有偏差；"
     "另：单证 9-8「电机 2.2×1.51×2.16 净6030/毛6390」无厂家对应箱，属孤箱，"
     "疑与 8# 减速机同批发运但厂家清单未单列"),
]

# 匹配阈值
TH_SCORE = 0.55      # 采纳下限
TH_MARGIN = 0.10     # 最优与次优最小差距（避免乱点鸳鸯）
DIM_TOL = 0.06       # 尺寸相对误差容限


def norm_box(no):
    """箱号归一：'2#'->'2'，'箱2'->'2'，'9-2'->'9-2'，全角转半角。"""
    s = str(no or "").strip()
    s = s.translate(str.maketrans("０１２３４５６７８９＃－～", "0123456789#-~"))
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"^(箱子?号?|no\.?|pkg\.?no\.?|case\.?no\.?)", "", s, flags=re.I)
    s = s.strip("#号箱")
    s = re.sub(r"^0+(?=\d)", "", s)          # 01 -> 1
    return s


def scheme_of(no):
    """编号体系判定：doc=单证号-箱序号；factory=厂家顺序号；other=其他。"""
    n = norm_box(no)
    if re.fullmatch(r"\d{1,2}-\d{1,3}", n):
        return "doc"
    if re.fullmatch(r"\d{1,3}", n):
        return "factory"
    return "other"


def _name_sim(a, b):
    a, b = str(a or ""), str(b or "")
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _dim_score(x, y):
    """尺寸相似度 0~1：三边都有且误差<6% 记满分。"""
    pairs = []
    for f in ("length_m", "width_m", "height_m"):
        a, b = x.get(f), y.get(f)
        if a and b:
            pairs.append(abs(a - b) / max(a, b))
    if not pairs:
        return 0.0, 0
    hit = sum(1 for d in pairs if d <= DIM_TOL)
    return hit / 3.0, len(pairs)


def _vol_score(x, y):
    a, b = x.get("volume_m3"), y.get("volume_m3")
    if a and b:
        return max(0.0, 1 - abs(a - b) / max(a, b))
    return 0.0


def _name_sim_multi(fb, db):
    """箱名相似度：取两侧所有来源名组合的最大值（同箱可能多源、名不同）。"""
    na = fb.get("names") or [fb.get("box_name") or ""]
    nb = db.get("names") or [db.get("box_name") or ""]
    best = 0.0
    for a in na:
        for b in nb:
            best = max(best, _name_sim(a, b))
    return best


def pair_score(fb, db):
    """厂家箱 vs 单证箱 综合得分。"""
    ds, ndim = _dim_score(fb, db)
    ns = _name_sim_multi(fb, db)
    vs = _vol_score(fb, db)
    score = 0.55 * ds + 0.35 * ns + 0.10 * vs
    # 尺寸三边全中但名称毫不相干 → 略降（可能是同规格不同物）
    if ds >= 1.0 and ns < 0.2:
        score -= 0.08
    return round(score, 4), ds, ns, vs, ndim


def load_boxes(con):
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT box_id, source_file_id, source_path, source_type, vendor, box_no, "
        "box_name, length_m, width_m, height_m, volume_m3, net_weight_kg, "
        "gross_weight_kg, item_count FROM packing_boxes")]
    return rows


def _richness(b):
    """记录信息量：有尺寸/重量越多越优先当代表。"""
    n = sum(1 for f in ("length_m", "width_m", "height_m", "volume_m3",
                        "net_weight_kg", "gross_weight_kg") if b.get(f))
    return (n, b.get("item_count") or 0)


GENERIC_NAME_KEYS = ("系统", "装箱", "清单", "PACKING", "PRE", "设备采购", "发货")


def _pick_name(names):
    """从同箱多个来源的箱名里挑最能代表箱内物品的：优先非通用名，其次较长者。"""
    cand = [n.strip() for n in names if n and n.strip()]
    if not cand:
        return ""
    specific = [n for n in cand if not any(k in n.upper() for k in GENERIC_NAME_KEYS)]
    pool = specific or cand
    return max(pool, key=len)


def dedupe(rows):
    """同厂商+同体系+同箱号 的多条记录（如一箱同时出现在单证与重尺表）合并为代表记录。

    代表记录保留全部 box_id 列表，写映射时一并挂上，避免"同箱两条记录只链一条"。
    names 保留全部来源的箱名（含通用系统名），供名称相似度取最大值。
    """
    groups = defaultdict(list)
    for b in rows:
        b["scheme"] = scheme_of(b["box_no"])
        b["norm"] = norm_box(b["box_no"])
        if not b["norm"]:
            continue
        groups[(b["vendor"], b["scheme"], b["norm"])].append(b)

    reps = []
    for _k, grp in groups.items():
        rep = dict(max(grp, key=_richness))
        rep["ids"] = [x["box_id"] for x in grp]
        rep["fids"] = sorted({x["source_file_id"] for x in grp})
        rep["names"] = sorted({(x["box_name"] or "").strip() for x in grp if (x["box_name"] or "").strip()})
        rep["box_name"] = _pick_name(rep["names"])
        reps.append(rep)
    return reps


def build_seed(con, reps, now):
    """写入人工确认映射，并为两端挂上 box_id。箱号对不上时按箱名兜底。"""
    out = []
    idx = defaultdict(list)
    for b in reps:
        idx[(b["vendor"], b["scheme"], b["norm"])].append(b)

    def find(vendor, no, sch):
        hit = idx.get((vendor, sch, norm_box(no)), [])
        if hit:
            return hit, ""
        return [], "库中无此箱号"

    for vendor, fno, dno, why in SEED:
        fb, nf = find(vendor, fno, "factory")
        db, nd = find(vendor, dno, "doc")
        miss = [x for x in (nf, nd) if x]
        out.append({
            "vendor": vendor, "factory_box_no": fno, "doc_box_no": dno,
            "factory_box_id": ";".join(i for x in fb for i in x["ids"]),
            "doc_box_id": ";".join(i for x in db for i in x["ids"]),
            "factory_file_id": ";".join(sorted({f for x in fb for f in x["fids"]})),
            "doc_file_id": ";".join(sorted({f for x in db for f in x["fids"]})),
            "match_method": "manual", "score": 1.0, "verified": 1,
            "remark": why, "created_at": now,
            "_miss": "、".join(miss),
        })
    return out


def auto_match(boxes):
    """同厂商内跨体系匹配：尺寸/名称。返回 (accepted, ambiguous, orphan)。

    采用「双向唯一最优」约束：一对映射只有在厂家箱侧与单证箱侧都互为最优时
    才采纳，避免同规格多箱互相乱点。
    """
    by_vendor = defaultdict(list)
    for b in boxes:
        if b["vendor"]:
            by_vendor[b["vendor"]].append(b)

    accepted, ambiguous, orphan = [], [], []
    for vendor, group in by_vendor.items():
        fac = [b for b in group if b["scheme"] == "factory"]
        doc = [b for b in group if b["scheme"] == "doc"]
        if not fac or not doc:
            continue

        scores = {}
        best_f, best_d = defaultdict(list), defaultdict(list)
        for i, fb in enumerate(fac):
            for j, db in enumerate(doc):
                s, ds, ns, vs, nd = pair_score(fb, db)
                scores[(i, j)] = (s, ds, ns, nd)
                best_f[i].append((s, j))
                best_d[j].append((s, i))

        used_f, used_d = set(), set()
        for (i, j), (s, ds, ns, nd) in sorted(scores.items(), key=lambda kv: -kv[1][0]):
            if s < TH_SCORE:
                break
            if i in used_f or j in used_d:
                continue
            top_f = max(best_f[i])[1]
            top_d = max(best_d[j])[1]
            if top_f != j or top_d != i:
                ambiguous.append((fac[i], doc[j], s, max(best_f[i])[0], "非双向唯一最优"))
                continue
            used_f.add(i)
            used_d.add(j)
            nd_hit = int(round(ds * 3))
            why = f"尺寸{nd_hit}/{nd}边命中，名称相似{ns:.2f}"
            accepted.append((fac[i], doc[j], s, why))

        for i, fb in enumerate(fac):
            if i not in used_f:
                orphan.append(("factory", fb))
        for j, db in enumerate(doc):
            if j not in used_d:
                orphan.append(("doc", db))
    return accepted, ambiguous, orphan


def sequential_match(boxes):
    """扫描件：文件名给厂家箱号区间(N#~M#)，OCR 给单证箱号 P-1~P-M，按升序对应。"""
    fac_range = {}
    for b in boxes:
        if b["source_type"] != "pdf_ocr":
            continue
        fn = os.path.basename(b["source_path"] or "")
        m = re.search(r"(\d+)\s*#\s*[~～至]\s*(\d+)\s*#", fn)
        if not m:
            continue
        a, z = int(m.group(1)), int(m.group(2))
        if 0 < z - a <= 60:
            fac_range[b["source_file_id"]] = (a, z, fn, b.get("vendor") or "")

    out = []
    for fid, (a, z, fn, vendor) in fac_range.items():
        grp = [b for b in boxes if b["source_file_id"] == fid and b["scheme"] == "doc"]
        if not grp:
            continue
        pref = Counter(b["norm"].split("-")[0] for b in grp)
        p = pref.most_common(1)[0][0]
        nums = sorted(int(b["norm"].split("-")[1]) for b in grp
                      if b["norm"].split("-")[0] == p)
        if nums != list(range(1, len(nums) + 1)):
            continue                      # 单证箱号非 1..N 连续，放弃顺序推断
        if len(nums) != z - a + 1:
            continue                      # 箱数与文件名区间不符，放弃
        for k in range(1, len(nums) + 1):
            out.append((f"{a+k-1}#", f"{p}-{k}", fid, fn, vendor))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--lookup", help="按箱号反查映射，如 2# 或 9-2")
    ap.add_argument("--xlsx", help="导出映射表到 xlsx")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.execute("PRAGMA busy_timeout=120000")
    for stmt in DDL.strip().split(";"):
        s = stmt.strip()
        if s:
            con.execute(s)
    con.commit()

    boxes = load_boxes(con)
    reps = dedupe(boxes)

    if args.lookup:
        q = norm_box(args.lookup)
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM packing_box_aliases WHERE factory_box_no=? OR doc_box_no=? "
            "OR factory_box_no LIKE ? OR doc_box_no LIKE ? ORDER BY verified DESC, score DESC",
            (args.lookup, args.lookup, f"%{q}%", f"%{q}%"))]
        print(f"\n反查「{args.lookup}」→ {len(rows)} 条映射\n")
        for r in rows:
            tag = "✔人工确认" if r["verified"] else "○待确认"
            print(f"  {tag} [{r['vendor']}] 厂家 {r['factory_box_no']:<6} ⇄ 单证 "
                  f"{r['doc_box_no']:<6} 分{r['score']:.2f} ({r['match_method']})")
            print(f"        {r['remark'][:100]}")
        if not rows:
            print("  (无映射记录；该箱号可能只有单一编号体系)")
        con.close()
        return

    now = datetime.now().isoformat(" ")

    # 1) 人工种子
    seeds = build_seed(con, reps, now)
    seed_rows = []
    print("== 1. 人工确认映射（种子）==")
    for s in seeds:
        flag = f"  ⚠ {s['_miss']}" if s["_miss"] else ""
        print(f"  ✔ {s['vendor']} 厂家{s['factory_box_no']:<4} ⇄ 单证{s['doc_box_no']:<5}{flag}")
        s.pop("_miss", None)
        seed_rows.append(s)
    print(f"  共 {len(seed_rows)} 条\n")

    # 2) 尺寸/名称自动匹配
    accepted, ambiguous, orphan = auto_match(reps)
    print("== 2. 尺寸+名称自动匹配 ==")
    print(f"  采纳 {len(accepted)} 对 | 歧义搁置 {len(ambiguous)} 对 | 未匹配端 {len(orphan)} 条")
    for fb, db, s, why in accepted[:15]:
        print(f"  ○ [{fb['vendor'][:12]}] {fb['box_no']:<6}({str(fb['box_name'])[:10]}) ⇄ "
              f"{db['box_no']:<6}({str(db['box_name'])[:10]}) 分{s:.2f} {why}")
    if ambiguous:
        print("  -- 歧义示例 --")
        for fb, db, s, s2, why in ambiguous[:6]:
            print(f"     ? {fb['box_no']} ⇄ {db['box_no']} 分{s:.2f} 次优{s2:.2f} {why}")
    print()

    # 3) 扫描件顺序推断
    seq = sequential_match(boxes)
    print("== 3. 扫描件顺序推断（待确认）==")
    print(f"  {len(seq)} 对")
    by_file = defaultdict(list)
    for fno, dno, fid, fn, vendor in seq:
        by_file[fn].append((fno, dno))
    for fn, pairs in list(by_file.items())[:8]:
        print(f"  ▣ {fn[:56]} → {len(pairs)} 对，例 {pairs[0][0]}⇄{pairs[0][1]}")
    print()

    if args.dry_run:
        print("[dry-run] 未写入数据库。")
        con.close()
        return

    if not args.yes:
        ans = input("确认写入映射表？[y/N]: ")
        if ans.strip().lower() not in ("y", "yes"):
            print("已取消。")
            con.close()
            return

    # 全量重建：SEED 是人工确认记录的唯一真源，且源文件被重解析后 box_id 会变，
    # 增量保留会导致映射指向已删除的箱记录。
    old = con.execute("SELECT COUNT(*) FROM packing_box_aliases").fetchone()[0]
    con.execute("DELETE FROM packing_box_aliases")
    print(f"[rebuild] 清空旧映射 {old} 条")

    ins = ("INSERT INTO packing_box_aliases (alias_id, vendor, factory_box_no, doc_box_no, "
           "factory_box_id, doc_box_id, factory_file_id, doc_file_id, match_method, score, "
           "verified, remark, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)")

    seed_f = {(s["vendor"], norm_box(s["factory_box_no"])) for s in seed_rows}
    written = 0

    for s in seed_rows:
        con.execute(ins, (str(uuid.uuid4()), s["vendor"], s["factory_box_no"], s["doc_box_no"],
                          s["factory_box_id"], s["doc_box_id"], s["factory_file_id"],
                          s["doc_file_id"], "manual", 1.0, 1, s["remark"][:200], now))
        written += 1

    for fb, db, s, why in accepted:
        if (fb["vendor"], norm_box(fb["box_no"])) in seed_f:
            continue                      # 已由人工种子覆盖，不再重复登记自动结果
        con.execute(ins, (str(uuid.uuid4()), fb["vendor"], fb["box_no"], db["box_no"],
                          ";".join(fb["ids"]), ";".join(db["ids"]),
                          ";".join(fb["fids"]), ";".join(db["fids"]),
                          "dims", s, 0, why[:200], now))
        written += 1

    for fno, dno, fid, fn, vendor in seq:
        con.execute(ins, (str(uuid.uuid4()), vendor, fno, dno, "", "", fid, fid,
                          "sequential", 0.6, 0,
                          f"扫描件顺序推断：文件名{fno[:6]}区间 ↔ OCR箱号{dno}，"
                          f"升序对应，方向待现场确认", now))
        written += 1

    con.commit()

    print(f"写入 {written} 条映射")
    for r in con.execute("SELECT match_method, COUNT(*) n, SUM(verified) v "
                         "FROM packing_box_aliases GROUP BY match_method"):
        print(f"  {r[0]:<12} {r[1]:>4} 条（已确认 {r[2] or 0}）")

    if args.xlsx:
        export_xlsx(con, args.xlsx)
    con.close()


def export_xlsx(con, path):
    import pandas as pd
    q = """SELECT a.vendor AS 供应商, a.factory_box_no AS 厂家箱号, a.doc_box_no AS 单证箱号,
                  a.match_method AS 匹配方式, a.score AS 置信分,
                  CASE a.verified WHEN 1 THEN '已确认' ELSE '待确认' END AS 状态,
                  b.box_name AS 箱名, b.length_m AS 长m, b.width_m AS 宽m, b.height_m AS 高m,
                  b.net_weight_kg AS 净重kg, b.gross_weight_kg AS 毛重kg,
                  b.item_count AS 箱内项数, a.remark AS 依据
           FROM packing_box_aliases a
           LEFT JOIN packing_boxes b ON b.box_id = a.doc_box_id OR b.box_id = a.factory_box_id
           ORDER BY a.verified DESC, a.vendor, a.factory_box_no"""
    df = pd.read_sql_query(q, con)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    df.to_excel(path, index=False)
    print(f"已导出 {len(df)} 行 → {path}")


if __name__ == "__main__":
    main()
