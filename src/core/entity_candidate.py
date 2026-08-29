"""工程实体候选提取（阶段1：只登记候选，不建立任何关系）。

从已导入资料中提取"候选工程实体"并登记到 engineering_entities 表。
原则（总纲十九 + 老板确认）：
- 发现实体 ≠ 确认实体 ≠ 建立关系
- 每个候选记录来源证据：来源文件/页码/位置/原始文字/图号/版本/提取方式/置信度
- 禁止自动关联（设备-基础/设备-厂家/设备-装箱单等一律不做）

提取来源：
1. CAD 语义分析结果（equipment 表）：已有设备/管道识别
2. 文档内容（document_contents）：设备表/材料表等含工程实体编码的行
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime

from src.database.connection import get_session, init_database
from src.database.models import (
    DocumentContentModel,
    EngineeringEntityModel,
    EquipmentModel,
    FileModel,
    PipeModel,
)
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.entity_candidate")

# 工程实体编号模式：如 K-205 / P-205 / FC0203DC01 / HX0203ME01 / 2A24A47DDA0203ME1MS1
ENTITY_CODE = re.compile(
    r"(?<![A-Z0-9])([A-Z]{1,4}-?\d{2,4}(?:[A-Z]{1,3}\d{0,3})?)(?![A-Z0-9])"
)
# 较长文件编码（如 2A24A47DDA0203ME1MS1）单独模式
FILE_CODE = re.compile(r"\b[A-Z0-9]{12,}\b")

# 实体类型关键词（用于粗分类）
TYPE_HINTS = {
    "equipment": ["窑", "磨", "机", "泵", "风机", "破碎", "收尘", "冷却",
                  "预热", "仓", "斗", "塔", "炉", "干燥", "混合", "计量"],
    "pipeline": ["管道", "管路", "管线", "配管"],
    "valve": ["阀", "蝶阀", "闸阀", "插板阀", "泄压阀"],
    "instrument": ["仪表", "液位计", "流量计", "压力", "温度计", "变送器"],
    "foundation": ["基础", "承台", "桩"],
    "structure": ["结构", "梁", "柱", "平台", "框架", "钢构"],
    "material": ["钢板", "螺栓", "法兰", "无缝钢管", "角钢", "槽钢", "钢筋"],
    "electrical": ["电机", "配电", "变压器", "变频", "开关柜", "电缆"],
}


def classify_entity(name: str) -> str:
    """按名称关键词粗分类（候选类型，非最终判定）。"""
    for etype, kws in TYPE_HINTS.items():
        if any(k in name for k in kws):
            return etype
    return "other"


def extract_candidates(rebuild: bool = False) -> dict:
    """扫描全部已入库资料，登记候选工程实体。

    Args:
        rebuild: True 时清空重提（默认增量，按文件去重）。

    Returns:
        {total, new, sources: {cad_equipment, cad_pipe, document}}
    """
    init_database()
    session = get_session()
    stats = {"total": 0, "new": 0,
             "cad_equipment": 0, "cad_pipe": 0, "document": 0}

    if rebuild:
        session.query(EngineeringEntityModel).delete()
        session.commit()

    # 已提取过的文件（避免重复）
    if not rebuild:
        done_files = {
            r[0] for r in session.query(
                EngineeringEntityModel.source_file_id).all() if r[0]
        }
    else:
        done_files = set()

    try:
        # ── 1. CAD 语义识别结果（equipment / pipes）────────────
        for eq in session.query(EquipmentModel).all():
            if eq.drawing_id in done_files:
                continue
            if not eq.equipment_no and not eq.equipment_name:
                continue
            _register(session, stats, entity_type="equipment",
                      entity_no=eq.equipment_no or "",
                      entity_name=eq.equipment_name or "",
                      source_file_id="", source_drawing_id=eq.drawing_id,
                      source_position=json.dumps({"x": eq.x, "y": eq.y}),
                      raw_text=f"{eq.equipment_no} {eq.equipment_name}".strip(),
                      extraction_method="cad_semantic",
                      confidence=eq.confidence or 0.5)
            stats["cad_equipment"] += 1
            done_files.add(eq.drawing_id)

        for pp in session.query(PipeModel).all():
            if pp.drawing_id in done_files:
                continue
            if not pp.pipe_no and not pp.diameter:
                continue
            _register(session, stats, entity_type="pipeline",
                      entity_no=pp.pipe_no or "",
                      entity_name=f"管道 DN{pp.diameter}" if pp.diameter else "管道",
                      source_file_id="", source_drawing_id=pp.drawing_id,
                      source_position=json.dumps({"x": pp.x, "y": pp.y}),
                      raw_text=f"{pp.pipe_no} {pp.diameter}".strip(),
                      extraction_method="cad_semantic",
                      confidence=pp.confidence or 0.5)
            stats["cad_pipe"] += 1

        # ── 2. 文档内容（设备表/材料表等）──────────────────────
        for doc in session.query(DocumentContentModel).all():
            if doc.file_id in done_files:
                continue
            n = _extract_from_document(session, stats, doc)
            done_files.add(doc.file_id)

        session.commit()
    finally:
        session.close()

    logger.info(f"实体候选提取: 新 {stats['new']} "
                f"(CAD设备 {stats['cad_equipment']}, "
                f"CAD管道 {stats['cad_pipe']}, 文档 {stats['document']})")
    return stats


def _extract_from_document(session, stats, doc) -> int:
    """从文档内容中提取候选实体（设备表行等）。"""
    content = doc.content or ""
    lines = content.splitlines()
    n = 0
    for line in lines:
        # 设备表行: 编码 | 名称 | ...
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if len(cells) < 2:
            continue
        code = cells[0]
        name = cells[1]
        # 编码需含字母+数字（如 K-205, FC0203DC01）；纯"设备表"标题跳过
        if not re.search(r"[A-Za-z]{2,}\d", code):
            continue
        if len(code) > 30 or len(name) > 40:
            continue
        if code in ("设备编号", "规格型号", "设备名称", "项目名称", "设备表"):
            continue
        etype = classify_entity(name)
        _register(session, stats, entity_type=etype,
                  entity_no=code, entity_name=name,
                  source_file_id=doc.file_id,
                  source_drawing_id="",
                  source_page=doc.title,
                  source_position="",
                  raw_text=f"{code} {name}",
                  extraction_method="document_table",
                  confidence=0.6)
        n += 1
    stats["document"] += n
    return n


def _register(session, stats, entity_type, entity_no, entity_name,
              source_file_id, source_drawing_id, source_position,
              raw_text, extraction_method, confidence,
              source_page: str = ""):
    """登记一个候选实体（同来源同编号去重）。"""
    q = session.query(EngineeringEntityModel).filter(
        EngineeringEntityModel.entity_no == entity_no)
    if source_file_id:
        q = q.filter(EngineeringEntityModel.source_file_id == source_file_id)
    else:
        q = q.filter(EngineeringEntityModel.source_drawing_id == source_drawing_id)
    if q.first():
        return
    session.add(EngineeringEntityModel(
        entity_id=str(uuid.uuid4()),
        entity_type=entity_type,
        entity_no=entity_no[:40],
        entity_name=entity_name[:100],
        source_file_id=source_file_id,
        source_drawing_id=source_drawing_id,
        source_page=source_page or "",
        source_position=source_position or "",
        raw_text=raw_text[:300],
        drawing_no="",
        file_version=1,
        extraction_method=extraction_method,
        confidence=min(float(confidence or 0.5), 1.0),
        created_at=datetime.now(),
    ))
    stats["new"] += 1


def list_candidates(entity_type: str | None = None, limit: int = 100) -> list[dict]:
    """列出候选实体（只读查询）。"""
    init_database()
    session = get_session()
    try:
        q = session.query(EngineeringEntityModel)
        if entity_type:
            q = q.filter(EngineeringEntityModel.entity_type == entity_type)
        rows = q.order_by(EngineeringEntityModel.entity_no).limit(limit).all()
        out = []
        for r in rows:
            file_name = ""
            if r.source_file_id:
                f = session.query(FileModel).filter(
                    FileModel.file_id == r.source_file_id).first()
                if f:
                    file_name = f.original_name
            out.append({
                "entity_type": r.entity_type,
                "entity_no": r.entity_no,
                "entity_name": r.entity_name,
                "source_file": file_name,
                "source_drawing_id": r.source_drawing_id,
                "raw_text": r.raw_text,
                "extraction_method": r.extraction_method,
                "confidence": r.confidence,
            })
        return out
    finally:
        session.close()


def count_candidates() -> dict:
    """候选实体统计（按类型）。"""
    from sqlalchemy import func

    init_database()
    session = get_session()
    try:
        rows = (
            session.query(
                EngineeringEntityModel.entity_type,
                func.count(EngineeringEntityModel.entity_id),
            )
            .group_by(EngineeringEntityModel.entity_type)
            .all()
        )
        total = session.query(func.count(EngineeringEntityModel.entity_id)).scalar()
        return {"total": total, "by_type": dict(rows)}
    finally:
        session.close()
