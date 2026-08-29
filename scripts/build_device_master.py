"""阶段 3：从 equipment_tags 构建 device_master / device_occurrences（跨图对齐）。

策略：
- 按 tag_no 归一化后聚合；保留每次出现的图纸坐标。
- 子系统取出现频次最高者；名称优先从 packing_items.equip_name 回填，
  否则保留 tag_no 作为占位（阶段 4 再逐步清洗）。
- 类别从位号编码推断（ME/DC/HX/TK/PM/FC/CF/...）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.database.connection import get_engine, get_session
from src.database.models import DeviceMasterModel, DeviceOccurrenceModel, EquipmentTagModel
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.scripts.build_device_master")

CATEGORY_MAP = {
    "ME": "机械设备/电机",
    "DC": "配电柜",
    "HX": "换热器",
    "TK": "储罐/容器",
    "PM": "泵",
    "FC": "风机",
    "CF": "压缩机/风机",
    "VA": "阀门",
    "PI": "压力仪表",
    "TI": "温度仪表",
    "FI": "流量仪表",
    "LI": "液位仪表",
    "AI": "分析仪表",
    "SI": "速度仪表",
}


def normalize_tag(tag: str) -> str:
    """标准化位号：大写、去空格、统一连字符/下划线为空。"""
    return re.sub(r"[-_\s]", "", tag).upper()


def infer_category(tag: str) -> str | None:
    """从位号编码推断设备大类。"""
    # 匹配 2字母 + 4数字子系统 + 2字母类别 + 数字
    m = re.match(r"^[A-Z]{2}\d{4}([A-Z]{2})\d+", tag.upper())
    if m:
        code = m.group(1)
        return CATEGORY_MAP.get(code, code)
    # 管道编号 P01-PP-01AC1
    if tag.upper().startswith("P"):
        return "管道"
    return None


def infer_subsystem(tag: str) -> str | None:
    """从位号前段推断子系统编号（如 FC0203ME01 -> 0203）。"""
    m = re.match(r"^[A-Z]{2}(\d{4})[A-Z]{2}", tag.upper())
    if m:
        return m.group(1)
    return None


def build(yes: bool = False):
    engine = get_engine()
    session = get_session()

    # 读取全部 equipment_tags + 对应 texts 名称
    logger.info("读取 equipment_tags 与 packing_items 名称...")
    rows = session.execute(text("""
        SELECT
            e.tag_id, e.drawing_id, e.tag_no, e.tag_type,
            e.x, e.y, e.height, e.layer, e.text_id, e.subsystem_no,
            t.text_content
        FROM equipment_tags e
        LEFT JOIN texts t ON t.text_id = e.text_id
    """)).fetchall()

    # 预取 packing_items 名称（packing_no 关联后阶段再处理，这里只做名称映射）
    # 注意：packing_items 无 tag_no，只有 equip_name；用 equip_name 与 tag_no 无直接键
    # 因此 stage3 名称占位策略：出现频次最高的 text_content 就是位号本身

    logger.info(f"equipment_tags 共 {len(rows)} 行")

    grouped: dict[str, list[dict]] = {}
    for r in rows:
        tag = (r.tag_no or "").strip()
        if not tag:
            continue
        norm = normalize_tag(tag)
        grouped.setdefault(norm, []).append({
            "tag_id": r.tag_id,
            "drawing_id": r.drawing_id,
            "tag_no": tag,
            "tag_type": r.tag_type,
            "x": r.x,
            "y": r.y,
            "height": r.height,
            "layer": r.layer,
            "text_id": r.text_id,
            "text_content": r.text_content or tag,
            "subsystem_no": (r.subsystem_no or "").strip() or infer_subsystem(tag),
        })

    logger.info(f"归一化后唯一位号: {len(grouped)}")

    if not yes:
        print(f"\n[DRY-RUN] 将生成 {len(grouped)} 条 device_master / {len(rows)} 条 device_occurrences")
        sample_items = list(grouped.items())[:10]
        for norm, items in sample_items:
            sub_counter = Counter(i["subsystem_no"] for i in items if i["subsystem_no"])
            main_sub = sub_counter.most_common(1)[0][0] if sub_counter else ""
            print(f"  {norm}: {len(items)} 次出现, 主属子系统 {main_sub}, 跨 {len(set(i['drawing_id'] for i in items))} 张图")
        return

    # 清空旧数据（幂等）
    session.execute(text("DELETE FROM device_occurrences"))
    session.execute(text("DELETE FROM device_master"))
    session.commit()
    logger.info("已清空旧 device_master / device_occurrences")

    total_occ = 0
    for norm, items in grouped.items():
        # 主属子系统：频次最高
        sub_counter = Counter(i["subsystem_no"] for i in items if i["subsystem_no"])
        main_sub = sub_counter.most_common(1)[0][0] if sub_counter else ""

        # 名称：取 text_content 频次最高者（通常是位号本身，阶段4再回填）
        name_counter = Counter(i["text_content"] for i in items)
        name = name_counter.most_common(1)[0][0] if name_counter else norm
        # 如果最频繁的就是位号，且 equip_name 无可用值，name 保持 tag_no

        drawing_ids = set(i["drawing_id"] for i in items)
        xs = [i["x"] for i in items if i["x"] is not None]
        ys = [i["y"] for i in items if i["y"] is not None]

        category = infer_category(items[0]["tag_no"])
        tag_display = items[0]["tag_no"]

        device_id = str(uuid.uuid4())
        dm = DeviceMasterModel(
            device_id=device_id,
            tag_no=tag_display,
            normalized_tag=norm,
            category=category,
            subsystem_no=main_sub,
            name=name,
            drawing_count=len(drawing_ids),
            occurrence_count=len(items),
            bbox_min_x=min(xs) if xs else None,
            bbox_min_y=min(ys) if ys else None,
            bbox_max_x=max(xs) if xs else None,
            bbox_max_y=max(ys) if ys else None,
            confidence=0.7 if len(items) > 1 else 0.5,
            source="equipment_tags aggregation",
        )
        session.add(dm)

        for item in items:
            occ = DeviceOccurrenceModel(
                occurrence_id=str(uuid.uuid4()),
                device_id=device_id,
                drawing_id=item["drawing_id"],
                file_id=None,
                tag_no=item["tag_no"],
                x=item["x"],
                y=item["y"],
                z=None,
                text_content=item["text_content"],
                layer=item["layer"],
                source="equipment_tags",
                confidence=0.7 if len(items) > 1 else 0.5,
            )
            session.add(occ)
            total_occ += 1

        if total_occ % 2000 == 0:
            session.commit()
            logger.info(f"已写入 {total_occ} 条出现记录...")

    session.commit()
    logger.info(f"device_master {len(grouped)} 条, device_occurrences {total_occ} 条写入完成")
    session.close()


def main():
    parser = argparse.ArgumentParser(description="构建 device_master 跨图设备主数据")
    parser.add_argument("--yes", action="store_true", help="正式写入数据库")
    args = parser.parse_args()
    build(yes=args.yes)


if __name__ == "__main__":
    main()
