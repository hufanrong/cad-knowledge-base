# -*- coding: utf-8 -*-
"""厂家装箱清单结构化 → packing_boxes / packing_box_items

与 build_packing_lists.py 互补：
  - build_packing_lists.py：按 JH 计划单号维度（到货跟踪汇总表）
  - 本脚本：按「箱号」维度（厂家随箱装箱清单 / 重尺表），
            每箱含 尺寸 / 净重 / 毛重 / 体积 + 箱内物品明细

支持格式：
  1. docx  装箱清单（序号|名称|数量|单位|备注 + "箱号：N#" + 尺寸行）
  2. xlsx/xls 装箱单/重尺表（列名含 箱子编号/箱号/长/宽/高/净重/毛重）
  3. HTML 伪 .xls（Excel 另存为 HTML，pandas.read_html，表头在 df.columns）

设计原则：
  - 只新增表，不动现有 packing_lists / packing_items
  - 幂等：按源文件 sha1(路径) 定向清理重插
  - 只读源文件，不改原始资料
  - 置信度标注：结构化列命中=0.9；启发式推断=0.6

用法:
    python scripts/parse_vendor_packing.py --dry-run
    python scripts/parse_vendor_packing.py --yes
    python scripts/parse_vendor_packing.py --root "D:/xxx" --dry-run
"""
import argparse
import hashlib
import os
import re
import sqlite3
import uuid
from collections import Counter
from datetime import datetime

DB = r"D:/WorkBuddy/work/data/knowledge_base/database/cadkb.db"
DEFAULT_ROOT = r"D:/Users/hufanrong/Desktop/安装资料"

DDL = """
CREATE TABLE IF NOT EXISTS packing_boxes (
    box_id          TEXT PRIMARY KEY,
    source_file_id  TEXT,
    source_path     TEXT,
    source_type     TEXT,
    contract_no     TEXT,
    doc_no          TEXT,
    order_no        TEXT,
    box_no          TEXT,
    packing_no      TEXT,
    box_name        TEXT,
    length_m        REAL,
    width_m         REAL,
    height_m        REAL,
    volume_m3       REAL,
    net_weight_kg   REAL,
    gross_weight_kg REAL,
    item_count      INTEGER DEFAULT 0,
    vendor          TEXT,
    remark          TEXT,
    confidence      REAL,
    created_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_pbox_no   ON packing_boxes(box_no);
CREATE INDEX IF NOT EXISTS idx_pbox_doc  ON packing_boxes(doc_no);
CREATE INDEX IF NOT EXISTS idx_pbox_src  ON packing_boxes(source_file_id);
CREATE INDEX IF NOT EXISTS idx_pbox_name ON packing_boxes(box_name);

CREATE TABLE IF NOT EXISTS packing_box_items (
    item_id        TEXT PRIMARY KEY,
    box_id         TEXT,
    box_no         TEXT,
    source_file_id TEXT,
    seq            INTEGER,
    item_name      TEXT,
    qty            TEXT,
    unit           TEXT,
    remark         TEXT,
    confidence     REAL,
    created_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_pbitem_box  ON packing_box_items(box_id);
CREATE INDEX IF NOT EXISTS idx_pbitem_name ON packing_box_items(item_name);
CREATE INDEX IF NOT EXISTS idx_pbitem_src  ON packing_box_items(source_file_id);
"""

COLMAP = {
    "box_no": ["箱子编号", "箱号", "箱单号", "箱编号", "编号", "箱子", "case no", "box no", "箱"],
    "box_name": ["箱子品名", "零件名称", "物品名称", "物料名称", "设备名称", "货物名称",
                 "品名名称", "货物明细", "品名", "名称", "零件", "货物", "description"],
    "qty": ["零件数量", "数量", "件数", "数  量"],
    "unit": ["零件单位", "单位"],
    "length_m": ["长(m)", "长（m）", "长度", "外形尺寸长", "长", "l(m)", "长mm"],
    "width_m": ["宽(m)", "宽（m）", "宽度", "外形尺寸宽", "宽", "w(m)", "宽mm"],
    "height_m": ["高(m)", "高（m）", "高度", "外形尺寸高", "高", "h(m)", "高mm"],
    "net_weight_kg": ["净重(kg)", "净重（kg）", "净重", "n.w.", "净重kg"],
    "gross_weight_kg": ["毛重(kg)", "毛重（kg）", "毛重", "g.w.", "毛重kg"],
    "volume_m3": ["体积(m³)", "体积", "cbm", "体积m3"],
    "spec": ["规格", "规格型号", "型号", "材质"],
}


def file_id_of(path: str) -> str:
    """源文件标识：按文件内容 sha1（而非路径），使同一文件的多个副本自动合并去重。"""
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return "src_" + h.hexdigest()[:16]
    except Exception:
        norm = os.path.normcase(os.path.abspath(path)).replace("\\", "/")
        return "src_" + hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def _norm(s) -> str:
    return re.sub(r"\s+", "", str(s or "")).lower()


def to_float(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            f = float(v)
            return None if f != f else f
        except Exception:
            return None
    s = str(v).strip()
    if not s or s in ("-", "—", "/", "无", "nan", "None"):
        return None
    s = s.replace(",", "").replace("，", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    try:
        return float(m.group(0)) if m else None
    except Exception:
        return None


def match_col(header_cells):
    """表头行 → {标准字段: 列索引}。精确匹配优先，其次包含匹配。"""
    mapping = {}
    norm = [_norm(c) for c in header_cells]
    # 第一轮：精确等于别名
    for field, aliases in COLMAP.items():
        for i, cell in enumerate(norm):
            if not cell:
                continue
            for alias in aliases:
                if cell == _norm(alias):
                    mapping.setdefault(field, i)
                    break
            if field in mapping:
                break
    # 第二轮：包含（仅对未命中的字段，且别名>=3字符避免误配）
    for field, aliases in COLMAP.items():
        if field in mapping:
            continue
        for i, cell in enumerate(norm):
            if not cell:
                continue
            for alias in aliases:
                a = _norm(alias)
                if len(a) >= 3 and a in cell:
                    mapping.setdefault(field, i)
                    break
            if field in mapping:
                break
    return mapping


RE_DIM = re.compile(r"(\d{2,5}(?:\.\d+)?)\s*[x×X*]\s*(\d{2,5}(?:\.\d+)?)\s*[x×X*]\s*(\d{2,5}(?:\.\d+)?)")
RE_BOXNO = re.compile(r"箱\s*号\s*[：:]\s*([0-9A-Za-z\-#]+)")
RE_CONTRACT = re.compile(r"合同编号\s*[：:]?\s*([0-9A-Za-z\-]{4,})")
RE_DOCNO = re.compile(r"\b(MNN-[A-Z]{2}-\d+[a-z]?(?:-\d+)?)\b")
RE_ORDER = re.compile(r"\b(85\d{8})\b")


def dims_from_text(text: str):
    m = RE_DIM.search(text or "")
    if not m:
        return None
    vals = []
    for i in (1, 2, 3):
        v = float(m.group(i))
        vals.append(v / 1000.0 if v > 20 else v)   # >20 视为毫米
    return tuple(vals)


def norm_dim(v):
    if v is None:
        return None
    return v / 1000.0 if v > 20 else v


# 常见厂商关键词（用于从路径/文件名识别供应商）
VENDOR_HINTS = [
    "龙净环保", "荥阳矿机", "河南省荥阳市矿山机械制造厂", "赛恩斯", "西安三瑞", "江苏鹏飞",
    "沈重华扬", "厦门托力托", "托力托", "双剑风机", "江西华欣", "滁州安瑞", "章丘风机",
    "美卓", "上海英格索兰", "英格索兰", "江苏矩烽", "北矿机电", "鼎峰搅拌", "宙斯泵业",
    "石家庄工业泵厂", "兰州电机", "江苏鼎峰", "大一重工", "朝阳腾达", "江苏华欣",
]
VENDOR_SUFFIX = ("有限公司", "公司", "集团", "机械", "环保", "科技", "重工", "泵业", "风机", "制造厂")


def guess_vendor(path: str) -> str:
    """供应商识别优先级：
    1) 路径中「厂家资料」的下一级目录（最可靠）
    2) 路径/文件名命中已知厂商关键词
    3) 路径中包含公司类后缀的目录名
    4) 退化：上级目录名
    """
    norm = os.path.normpath(path).replace("\\", "/")
    parts = norm.split("/")

    if "厂家资料" in parts:
        i = parts.index("厂家资料")
        if i + 1 < len(parts):
            return parts[i + 1]

    for hint in VENDOR_HINTS:
        if hint in norm:
            return hint

    # 从后往前找带公司后缀的目录/文件名片段
    for seg in reversed(parts[:-1]):
        if any(suf in seg for suf in VENDOR_SUFFIX):
            return seg

    # 识别不出真实厂商 → 留空（不把"窑尾/酸化窑/20241122"等部位或日期目录误当供应商）
    return ""


def guess_area(path: str) -> str:
    """工程部位/区域（用于 vendor 未识别时补充上下文）。"""
    parts = os.path.normpath(path).replace("\\", "/").split("/")
    # 优先取「安装资料」下一级的二级目录，如 冶炼厂/窑尾
    if "安装资料" in parts:
        i = parts.index("安装资料")
        segs = [s for s in parts[i + 1:-1] if s]
        if len(segs) >= 2:
            return f"{segs[0]}/{segs[1]}"
        if segs:
            return segs[0]
    return os.path.basename(os.path.dirname(path))


def _mk_box(**kw):
    """统一箱字典结构，避免缺键。"""
    box = {
        "box_no": "", "packing_no": "", "box_name": "",
        "length_m": None, "width_m": None, "height_m": None,
        "volume_m3": None, "net_weight_kg": None, "gross_weight_kg": None,
        "contract_no": "", "doc_no": "", "order_no": "",
        "remark": "", "confidence": 0.6, "items": [],
    }
    box.update(kw)
    return box


# ───────────────────────── docx 解析 ─────────────────────────
def parse_docx(path: str):
    from docx import Document

    doc = Document(path)
    paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    all_text = "\n".join(paras)

    contract = RE_CONTRACT.search(all_text)
    docno = RE_DOCNO.search(all_text)
    order = RE_ORDER.search(all_text)
    boxes = []
    for t_idx, table in enumerate(doc.tables):
        rows = []
        for row in table.rows:
            cells = [c.text.strip().replace("\n", " ") for c in row.cells]
            compact = []
            for c in cells:
                if not compact or compact[-1] != c:
                    compact.append(c)
            rows.append(compact)
        flat = "\n".join(" | ".join(r) for r in rows)

        m = RE_BOXNO.search(flat) or RE_BOXNO.search(all_text)
        if not m:
            # 无「箱号：X」标记 → 不是装箱清单（避免把普通技术规格表误当箱单）
            continue
        box_no = m.group(1)
        dims = dims_from_text(flat)
        # 合同号/单证号不仅可能在段落，也可能只出现在表格单元格内（如"合同编号:2025-191"）
        if not contract:
            contract = RE_CONTRACT.search(flat)
        if not docno:
            docno = RE_DOCNO.search(flat)
        if not order:
            order = RE_ORDER.search(flat)

        # 表头检测：必须是真正的物品表头（含 名称 且 数量/单位，或 序号+名称）。
        # 不能用 match_col 的 box_name 判断——"货物明细"等标题行也会命中。
        header_idx = None
        for i, r in enumerate(rows):
            joined = _norm("".join(r))
            if ("名称" in joined and ("数量" in joined or "单位" in joined)) or \
               ("序号" in joined and "名称" in joined):
                header_idx = i
                break

        name_i = qty_i = unit_i = remark_i = None
        if header_idx is not None:
            for j, c in enumerate(rows[header_idx]):
                c2 = _norm(c)
                if name_i is None and c2 in ("名称", "品名", "货物名称", "设备名称"):
                    name_i = j
                elif qty_i is None and c2 in ("数量", "件数", "数  量"):
                    qty_i = j
                elif unit_i is None and c2 in ("单位",):
                    unit_i = j
                elif remark_i is None and c2 in ("备注", "说明"):
                    remark_i = j

        start = (header_idx + 1) if header_idx is not None else 0
        items, seq = [], 0
        for r in rows[start:]:
            if not r or not any(r):
                continue
            joined = " | ".join(r)
            if any(k in joined for k in ("随车携带装箱清单", "合计", "小计", "河南省荥阳市矿山机械")):
                continue
            filled = [x for x in r if x]
            # 纯尺寸行跳过
            if len(filled) == 1 and RE_DIM.search(filled[0]) and not re.search(r"[\u4e00-\u9fa5]{2,}", filled[0]):
                continue
            nm = r[name_i] if (name_i is not None and name_i < len(r)) else ""
            if not nm:
                for c in r:
                    if re.search(r"[\u4e00-\u9fa5A-Za-z]", c) and not re.fullmatch(r"[\d.\-#]+", c):
                        nm = c
                        break
            nm = str(nm).strip()
            if not nm or re.fullmatch(r"[\d.\-]+", nm) or _norm(nm) in ("货物明细", "序号", "名称", "品名"):
                continue
            qty = r[qty_i] if (qty_i is not None and qty_i < len(r)) else ""
            unit = r[unit_i] if (unit_i is not None and unit_i < len(r)) else ""
            remark = ""
            if remark_i is not None and remark_i < len(r):
                remark = r[remark_i]
            elif len(r) >= 5:
                remark = r[-1]
            if _norm(remark) in (_norm(nm), _norm(qty)):
                remark = ""
            seq += 1
            items.append({"seq": seq, "item_name": nm[:120], "qty": str(qty)[:20],
                          "unit": str(unit)[:10], "remark": str(remark)[:120]})

        if not items:
            continue
        boxes.append(_mk_box(
            box_no=str(box_no),
            box_name=(items[0]["item_name"] if items else "")[:80],
            length_m=dims[0] if dims else None,
            width_m=dims[1] if dims else None,
            height_m=dims[2] if dims else None,
            contract_no=contract.group(1) if contract else "",
            doc_no=docno.group(1) if docno else "",
            order_no=order.group(1) if order else "",
            confidence=0.9 if dims else 0.7,
            items=items,
        ))
    return boxes


# ───────────────────────── Excel / HTML 解析 ─────────────────────────
def parse_excel(path: str):
    import pandas as pd

    with open(path, "rb") as f:
        head = f.read(300)
    is_html = b"<html" in head.lower() or b"<!doctype" in head.lower()

    frames = []   # (df, has_header)
    try:
        if is_html:
            for df in pd.read_html(path):
                frames.append((df, True))      # read_html 已把首行当表头
            source_type = "xls_html"
        elif path.lower().endswith(".xls"):
            xl = pd.ExcelFile(path, engine="xlrd")
            for sh in xl.sheet_names:
                frames.append((pd.read_excel(path, sheet_name=sh, header=None, engine="xlrd"), False))
            source_type = "xls_packlist"
        else:
            xl = pd.ExcelFile(path, engine="openpyxl")
            for sh in xl.sheet_names:
                frames.append((pd.read_excel(path, sheet_name=sh, header=None, engine="openpyxl"), False))
            source_type = "xlsx_packlist"
    except Exception as e:
        return [], f"读取失败: {e}"

    boxes = []
    for df, has_header in frames:
        if df is None or df.empty:
            continue

        header_idx, colmap = None, {}
        if has_header:
            cm = match_col(list(df.columns))
            if "box_no" in cm:
                header_idx, colmap = -1, cm      # -1 表示表头在 columns
        if not colmap:
            rows = df.fillna("").values.tolist()
            for i, r in enumerate(rows[:15]):
                cm = match_col(r)
                if "box_no" in cm:
                    header_idx, colmap = i, cm
                    break
        if not colmap or "box_no" not in colmap:
            continue

        if has_header:
            data_rows = df.fillna("").values.tolist()
            header_cells = list(df.columns)
        else:
            all_rows = df.fillna("").values.tolist()
            data_rows = all_rows[header_idx + 1:]
            header_cells = all_rows[header_idx]

        # 按箱号聚合：零件级明细表同一箱号会有多行（每行一个零件）
        agg, order = {}, []
        for r in data_rows:
            if not r or not any(str(x).strip() for x in r):
                continue

            def cell(field):
                idx = colmap.get(field)
                if idx is None or idx >= len(r):
                    return ""
                return r[idx]

            box_no = re.sub(r"\s+", "", str(cell("box_no")).strip())
            if not box_no or box_no in ("箱子编号", "箱号", "合计", "小计", "nan", "None"):
                continue
            if len(box_no) > 20 or re.search(r"[，。；、！？]", box_no):
                continue
            if not re.search(r"[\dA-Za-z]", box_no):
                continue

            name = str(cell("box_name")).strip()
            if name in ("nan", "None"):
                name = ""
            qty = str(cell("qty")).strip()
            unit = str(cell("unit")).strip()
            spec = str(cell("spec")).strip()
            if qty == "nan":
                qty = ""
            if unit == "nan":
                unit = ""
            if spec == "nan":
                spec = ""

            if box_no not in agg:
                agg[box_no] = _mk_box(box_no=box_no[:40])
                order.append(box_no)
            box = agg[box_no]

            # 尺寸/重量/体积：同箱多行时取首个非空值
            for field, val in (
                ("length_m", norm_dim(to_float(cell("length_m")))),
                ("width_m", norm_dim(to_float(cell("width_m")))),
                ("height_m", norm_dim(to_float(cell("height_m")))),
                ("volume_m3", to_float(cell("volume_m3"))),
                ("net_weight_kg", to_float(cell("net_weight_kg"))),
                ("gross_weight_kg", to_float(cell("gross_weight_kg"))),
            ):
                if box[field] is None and val is not None:
                    box[field] = val

            if name:
                if not box["box_name"]:
                    box["box_name"] = name[:80]
                box["items"].append({
                    "seq": len(box["items"]) + 1,
                    "item_name": name[:120],
                    "qty": qty[:20],
                    "unit": unit[:10],
                    "remark": spec[:120],
                })

        # 汇总本 sheet 的箱
        for bno in order:
            b = agg[bno]
            # 丢弃完全无信息的行（无品名、无尺寸、无重量）——多为表头/合计残留
            if not b["items"] and not any([b["length_m"], b["net_weight_kg"],
                                           b["gross_weight_kg"], b["volume_m3"]]):
                continue
            b["confidence"] = 0.9 if any([b["length_m"], b["net_weight_kg"],
                                          b["gross_weight_kg"], b["volume_m3"]]) else 0.7
            boxes.append(b)
    return boxes, source_type


def collect_files(root: str):
    """收集所有可解析 Office 文件（不依赖文件名，靠内容判定是否装箱单）。

    原因：像「320单证9箱石灰乳制备重量.xls」这类文件名不含「装箱/箱单」关键词，
    但确是装箱明细表；按文件名筛选会漏。改为全量收集 + 解析阶段按表头识别。
    """
    exts = (".docx", ".xlsx", ".xls")
    out = []
    for dirpath, _dn, filenames in os.walk(root):
        for fn in filenames:
            low = fn.lower()
            if low.startswith("~$"):          # Office 临时锁文件
                continue
            if not low.endswith(exts):
                continue
            out.append(os.path.join(dirpath, fn))
    return sorted(out)


def parse_one(f):
    """返回 (boxes, source_type)"""
    if f.lower().endswith(".docx"):
        return parse_docx(f), "docx_manifest"
    boxes, stype = parse_excel(f)
    return boxes, stype


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--reset", action="store_true", help="清空 packing_boxes/items 后全量重建")
    args = ap.parse_args()

    files = collect_files(args.root)
    print(f"扫描根目录: {args.root}")
    print(f"待解析文件: {len(files)} 个\n")

    jobs = []          # (file_id, path, vendor, source_type, boxes)
    stats = Counter()
    failed, nobox, dups = [], [], []
    seen_fid = {}      # 内容 hash → 首次出现的相对路径（副本合并）

    for f in files:
        rel = os.path.relpath(f, args.root)
        try:
            boxes, stype = parse_one(f)
        except Exception as e:
            failed.append((rel, repr(e)[:120]))
            stats["fail"] += 1
            continue
        if not boxes:
            nobox.append(rel)
            stats["no_box"] += 1
            continue
        fid = file_id_of(f)
        if fid in seen_fid:
            # 同一文件的副本（内容 hash 相同），只保留首次出现
            dups.append((rel, seen_fid[fid]))
            stats["dup"] += 1
            continue
        seen_fid[fid] = rel
        jobs.append((fid, f, guess_vendor(f), stype, boxes))
        stats["ok"] += 1
        nitems = sum(len(b["items"]) for b in boxes)
        print(f"  ✓ [{stype}] {rel[:72]} → {len(boxes)} 箱 / {nitems} 项")

    n_boxes = sum(len(b) for _, _, _, _, b in jobs)
    n_items = sum(len(x["items"]) for _, _, _, _, b in jobs for x in b)

    print(f"\n汇总: 有效 {stats['ok']} 文件 | 重复副本合并 {stats['dup']} | "
          f"无可识别箱号 {stats['no_box']} | 失败 {stats['fail']}")
    print(f"箱级记录: {n_boxes} 条 | 箱内物品: {n_items} 条")

    if dups:
        print("\n重复副本合并（前5）:")
        for rel, first in dups[:5]:
            print(f"  ⇄ {rel[:60]}  同 {first[:40]}")

    if nobox:
        print("\n未识别箱号（前10）:")
        for rel in nobox[:10]:
            print(f"  · {rel[:80]}")
    if failed:
        print("\n解析失败（前5）:")
        for rel, err in failed[:5]:
            print(f"  ✗ {rel[:70]} → {err}")

    print("\n== 验收点：石灰乳制备 320单证 ==")
    hit = [(fid, p, v, st, bs) for fid, p, v, st, bs in jobs if "荥阳" in v]
    total = 0
    for fid, p, v, st, bs in hit:
        for b in bs:
            total += 1
            print(f"  [{st}] 箱{b['box_no']:<5} {b['box_name'][:14]:<14} "
                  f"{b['length_m']}×{b['width_m']}×{b['height_m']} "
                  f"净{b['net_weight_kg']} 毛{b['gross_weight_kg']} 项{len(b['items'])}")
    if not hit:
        print("  (未命中)")
    else:
        print(f"  合计 {total} 箱")

    if args.dry_run:
        print("\n[dry-run] 未写入数据库。")
        return

    if not args.yes:
        ans = input(f"\n即将写入 {n_boxes} 箱 / {n_items} 项，确认？[y/N]: ")
        if ans.strip().lower() not in ("y", "yes"):
            print("已取消。")
            return

    con = sqlite3.connect(DB)
    con.execute("PRAGMA busy_timeout=120000")
    for stmt in DDL.strip().split(";"):
        s = stmt.strip()
        if s:
            con.execute(s)

    now = datetime.now().isoformat(" ")
    if args.reset:
        old1 = con.execute("SELECT COUNT(*) FROM packing_boxes").fetchone()[0]
        old2 = con.execute("SELECT COUNT(*) FROM packing_box_items").fetchone()[0]
        con.execute("DELETE FROM packing_box_items")
        con.execute("DELETE FROM packing_boxes")
        print(f"[reset] 已清空旧记录 packing_boxes {old1} / items {old2}")
    else:
        src_ids = [j[0] for j in jobs]
        if src_ids:
            ph = ",".join("?" * len(src_ids))
            con.execute(f"DELETE FROM packing_box_items WHERE source_file_id IN ({ph})", tuple(src_ids))
            con.execute(f"DELETE FROM packing_boxes WHERE source_file_id IN ({ph})", tuple(src_ids))

    ins_box = ("INSERT INTO packing_boxes (box_id, source_file_id, source_path, source_type, contract_no, "
               "doc_no, order_no, box_no, packing_no, box_name, length_m, width_m, height_m, volume_m3, "
               "net_weight_kg, gross_weight_kg, item_count, vendor, remark, confidence, created_at) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    ins_item = ("INSERT INTO packing_box_items (item_id, box_id, box_no, source_file_id, seq, item_name, "
                "qty, unit, remark, confidence, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)")

    written_boxes = written_items = 0
    for fid, path, vendor, stype, boxes in jobs:
        area = "" if vendor else guess_area(path)   # 厂商未识别时记录工程部位
        for b in boxes:
            bid = str(uuid.uuid4())
            remark_val = b["remark"] or (f"[部位]{area}" if area else "")
            con.execute(ins_box, (
                bid, fid, path, stype, b["contract_no"], b["doc_no"], b["order_no"],
                b["box_no"], b["packing_no"], b["box_name"], b["length_m"], b["width_m"],
                b["height_m"], b["volume_m3"], b["net_weight_kg"], b["gross_weight_kg"],
                len(b["items"]), vendor, remark_val[:120], b["confidence"], now))
            written_boxes += 1
            for it in b["items"]:
                con.execute(ins_item, (
                    str(uuid.uuid4()), bid, b["box_no"], fid, it["seq"], it["item_name"],
                    it["qty"], it["unit"], it["remark"], b["confidence"], now))
                written_items += 1

    con.commit()
    n1 = con.execute("SELECT COUNT(*) FROM packing_boxes").fetchone()[0]
    n2 = con.execute("SELECT COUNT(*) FROM packing_box_items").fetchone()[0]
    print(f"\n本次写入 {written_boxes} 箱 / {written_items} 项")
    print(f"库内累计 packing_boxes {n1} / packing_box_items {n2}")
    con.close()


if __name__ == "__main__":
    main()
