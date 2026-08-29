"""为 CAD 图纸建立「同子项」逻辑关联（belongs_to_subsystem）。

子项聚类规则：以 4 位数字编号为唯一主键（文件名开头优先，其次 file_path 首个编号目录段兜底），
子项规范名取组内多数票（目录名段优先，文件名名段次之）。
关系写入 file_relations 表：file_a=files.file_id, file_b=子项键"编号 规范名"。
幂等：以 (relation_type, source) 定向清理后重插，可重复执行。

用法:
    python scripts/build_file_relations.py --dry-run   # 预演：只分析输出计划，不写库
    python scripts/build_file_relations.py --yes       # 正式写入（跳过交互确认）
    python scripts/build_file_relations.py             # 正式写入（展示计划后要求确认）
"""
import argparse
import re
import sys
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from src.database.connection import get_session, init_database
from src.database.models import FileRelationModel
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.build_relations")

RELATION_TYPE = "belongs_to_subsystem"
SOURCE = "subsystem_cluster"

# 手工纠正表：file_name -> 强制子项编号（处理文件名编号与目录编号冲突）
OVERRIDES = {
    # 实测唯一冲突：文件名 0508，物理目录 0408 除盐水站。以图纸自身编号 0508 为准。
    "0508 空压站-建筑图（增加厂房内电缆沟）20250911.dwg": "0508",
}

# 锚定开头，避免误匹配风管内嵌编号（如 2A24A47DDA0101ME1PW1-01 中的 0101）
FILENAME_SUBSYS_RE = re.compile(r"^(\d{4})\s*[-－—]?\s*(.*)$")
# 目录名段（如 "0101锂辉石精矿库" -> "锂辉石精矿库"）
DIR_SEG_RE = re.compile(r"^(\d{4})\s*[-－—]?\s*(.*)$")


def path_parts(p: str) -> list:
    return [x for x in str(p).replace("\\", "/").split("/") if x]


def first_numbered_dir(path: str):
    """file_path 中第一个以 4 位数字开头的目录段（路径根->叶顺序）。"""
    for seg in path_parts(path):
        if FILENAME_SUBSYS_RE.match(seg):
            return seg
    return None


def extract_number(file_name: str, file_path: str, original_name: str = "") -> tuple:
    """
    返回 (编号, 来源)：
      - OVERRIDES 命中 -> 强制编号 ("override")
      - 优先级1: file_name 开头 4 位数字 -> ("filename")
      - 优先级2: file_path 首个编号目录段 -> ("directory")
      - 均无 -> (None, None)
    """
    if original_name in OVERRIDES:
        return OVERRIDES[original_name], "override"
    m = FILENAME_SUBSYS_RE.match((file_name or "").strip())
    if m:
        return m.group(1), "filename"
    nd = first_numbered_dir(file_path)
    if nd:
        return nd[:4], "directory"
    return None, None


def dir_number_of(path: str):
    """file_path 首个编号目录段的编号（用于双源交叉验证）。"""
    nd = first_numbered_dir(path)
    return nd[:4] if nd else None


def dir_name_of(ndir: str) -> str:
    m = DIR_SEG_RE.match(ndir)
    return m.group(2).strip() if m else ""


def filename_name_of(file_name: str) -> str:
    m = FILENAME_SUBSYS_RE.match((file_name or "").strip())
    if not m:
        return ""
    seg = m.group(2).strip()
    return re.split(r"[-－—（(]", seg)[0].strip()


def canonical_key(number: str, group_drawings) -> str:
    """group_drawings: 该编号组 [(file_name, file_path, dir_seg, drawing_id, file_id, source), ...]。规范名多数票。"""
    dir_names = Counter(dir_name_of(dseg) for _, _, dseg, _, _, _ in group_drawings if dseg)
    fn_names = Counter(filename_name_of(fn) for fn, _, _, _, _, _ in group_drawings)
    for counter in (dir_names, fn_names):
        for name, _ in counter.most_common():
            if name:
                return f"{number} {name}"
    return number


def load_drawings():
    """只读加载 drawings + files 映射。返回 list[(drawing_id, file_name, file_path, file_id)]。"""
    import sqlite3

    conn = sqlite3.connect(
        "file:D:/WorkBuddy/work/data/knowledge_base/database/cadkb.db?mode=ro",
        uri=True, timeout=60,
    )
    conn.execute("PRAGMA busy_timeout=60000")
    rows = conn.execute(
        """
        SELECT d.drawing_id, d.file_name, d.file_path, f.file_id
        FROM drawings d
        LEFT JOIN files f ON f.drawing_id = d.drawing_id AND f.file_type='dwg'
        """
    ).fetchall()
    conn.close()
    return rows


def main():
    ap = argparse.ArgumentParser(description="建立图纸同子项逻辑关联")
    ap.add_argument("--dry-run", action="store_true", help="只分析输出计划，不写库")
    ap.add_argument("--yes", action="store_true", help="跳过交互确认直接写入")
    args = ap.parse_args()

    drawings = load_drawings()
    total = len(drawings)
    print(f"加载图纸: {total} 张", flush=True)

    # ---- 1. 分组 ----
    groups = {}   # number -> list[(file_name, file_path, dir_seg, drawing_id, file_id, source)]
    warnings = []
    no_file = 0
    for drawing_id, file_name, file_path, file_id in drawings:
        if not file_id:
            no_file += 1
            warnings.append(f"[缺失 files 映射] drawing_id={drawing_id} file={file_name}")
            continue
        number, source = extract_number(file_name, file_path, file_name)
        if not number:
            warnings.append(f"[无编号且无目录兜底] {file_name}")
            continue
        dir_seg = first_numbered_dir(file_path)
        dir_num = dir_number_of(file_path)
        # 双源交叉验证
        if source == "filename" and dir_num and dir_num != number:
            warnings.append(
                f"[编号冲突] {file_name}: 文件名 {number} vs 目录 {dir_num} (以文件名/OVERRIDES为准)"
            )
        if source == "override":
            pass
        groups.setdefault(number, []).append(
            (file_name, file_path, dir_seg, drawing_id, file_id, source)
        )

    # 多编号文件名（仅识别开头的子项编号序列，如 "0206~0207-..."、"0302、0303蒸发车间-..."；
    # 文件名后部的 8 位日期如 20250718 不是子项编号，不判多编号）
    for fn in {d[1] for d in drawings}:
        m_multi = re.match(r"^(\d{4})\s*[~～、,，]\s*(\d{4})", (fn or "").strip())
        if m_multi:
            warnings.append(f"[多编号文件名] {fn} -> 取首个编号 {m_multi.group(1)}")

    # ---- 2. 规范名与关系行 ----
    relations = []
    plan_rows = []  # (file_id, file_name, file_b, confidence, source_detail)
    for number, group in sorted(groups.items()):
        key = canonical_key(number, group)
        n = len(group)
        for file_name, file_path, dir_seg, drawing_id, file_id, src in group:
            dir_num = dir_number_of(file_path)
            # confidence 分级
            if src == "override":
                conf = 0.90
            elif src == "filename" and dir_num == number:
                conf = 0.95
            elif src == "filename":
                conf = 0.85
            else:  # directory 兜底
                conf = 0.70
            relations.append(
                (file_id, file_name, key, conf, src)
            )
            plan_rows.append((file_id, file_name, key, conf, src))

    print(f"分组数: {len(groups)} | 关系行数: {len(relations)} | 缺 files 映射: {no_file}", flush=True)
    print(f"警告数: {len(warnings)}", flush=True)

    # ---- 3. dry-run 输出计划 ----
    if args.dry_run:
        print("\n=== 分组计划（编号 规范名 | 图纸数） ===", flush=True)
        for number, group in sorted(groups.items()):
            key = canonical_key(number, group)
            print(f"  {key} | {len(group)} 张", flush=True)
        print("\n=== 警告清单 ===", flush=True)
        for w in warnings:
            print(f"  {w}", flush=True)
        print("\n[DRY-RUN] 未写库。确认无误后运行: python scripts/build_file_relations.py --yes", flush=True)
        return

    # ---- 4. 正式写入（确认 + 幂等） ----
    if not args.yes:
        print(f"\n即将写入 {len(relations)} 条 belongs_to_subsystem 关系到 file_relations 表。", flush=True)
        for number, group in sorted(groups.items()):
            key = canonical_key(number, group)
            print(f"  {key} | {len(group)} 张", flush=True)
        ans = input("确认写入？[y/N]: ").strip().lower()
        if ans not in ("y", "yes"):
            print("已取消。", flush=True)
            return

    init_database()
    s = get_session()
    try:
        s.execute(text("PRAGMA busy_timeout=60000"))
        # 幂等清理：只清本脚本来源的数据
        s.execute(
            text(
                "DELETE FROM file_relations "
                "WHERE relation_type=:rt AND source=:src"
            ),
            {"rt": RELATION_TYPE, "src": SOURCE},
        )
        objs = [
            FileRelationModel(
                rel_id=str(uuid.uuid4()),
                file_a=file_id,
                file_b=key,
                relation_type=RELATION_TYPE,
                confidence=conf,
                source=SOURCE,
                created_at=datetime.now(),
            )
            for file_id, file_name, key, conf, src in relations
        ]
        s.bulk_save_objects(objs)
        s.commit()
        print(f"已写入 {len(objs)} 条关系（rel_id 重新生成）。", flush=True)
    except Exception as e:
        s.rollback()
        print(f"写入失败，已回滚: {e}", flush=True)
        raise
    finally:
        s.close()

    print("\n=== 警告清单（供人工复核） ===", flush=True)
    for w in warnings:
        print(f"  {w}", flush=True)
    print("\n完成。验证 SQL 见计划文档第五节。", flush=True)


if __name__ == "__main__":
    main()
