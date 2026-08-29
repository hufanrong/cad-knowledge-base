"""设备档案聚合服务（阶段 3）。

按 tag_no 聚合跨图、跨文档信息，返回统一设备档案：
- 设备主数据（device_master）
- 出现位置（device_occurrences + 图纸名称 + 预览图路径 + 标高）
- 箱单/供应商/到货（packing_items + relation_candidates）
- 业务文档命中（relation_candidates 关联 document_contents/files）
- 同子系统相关图纸（get_related_files 修复后）

设计原则：
- 只读聚合现有表，不引入新关联关系。
- candidate 关系 status 为 pending 时明确标注"待确认"。
- 跨图坐标保留原图坐标系，2.5D 视图按当前图纸映射。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from src.database.connection import get_session
from src.database.models import (
    DeviceMasterModel,
    DeviceOccurrenceModel,
    DrawingModel,
)


def _file_id_for_drawing(drawing_id: str) -> str | None:
    session = get_session()
    try:
        row = session.execute(
            text("SELECT file_id FROM files WHERE drawing_id=:did LIMIT 1"),
            {"did": drawing_id},
        ).fetchone()
        return row[0] if row else None
    finally:
        session.close()


def _preview_path(drawing_id: str) -> str | None:
    p = Path(f"D:/WorkBuddy/work/data/knowledge_base/Preview/{drawing_id}.png")
    return str(p) if p.exists() else None


def _elevation_for_drawing(drawing_id: str) -> dict | None:
    session = get_session()
    try:
        row = session.execute(
            text("""SELECT datum_elevation, datum_type, raw_text, confidence, verified
                  FROM elevations WHERE drawing_id=:did
                  ORDER BY confidence DESC LIMIT 1"""),
            {"did": drawing_id},
        ).fetchone()
        if row:
            return {
                "datum_elevation": row[0],
                "datum_type": row[1],
                "raw_text": row[2],
                "confidence": row[3],
                "verified": bool(row[4]),
            }
        return None
    finally:
        session.close()


def _packing_for_tag(tag_no: str) -> list[dict]:
    """通过 relation_candidates.cand_type='equipment_packing' 关联 packing_items。"""
    session = get_session()
    try:
        rows = session.execute(
            text("""SELECT pi.packing_no, pi.equip_name, pi.vendor, pi.qty,
                           rc.confidence, rc.status, rc.evidence
                    FROM relation_candidates rc
                    JOIN packing_items pi ON pi.packing_no = rc.target_key
                    WHERE rc.cand_type = 'equipment_packing'
                      AND rc.entity_key = :tag
                    ORDER BY rc.confidence DESC"""),
            {"tag": tag_no},
        ).fetchall()
        out = []
        for r in rows:
            out.append({
                "packing_no": r[0],
                "equip_name": r[1],
                "vendor": r[2],
                "qty": r[3],
                "confidence": r[4],
                "status": r[5],
                "evidence": r[6],
            })
        return out
    finally:
        session.close()


def _documents_for_tag(tag_no: str) -> list[dict]:
    """通过 relation_candidates.cand_type='device_document' 关联 files/document_contents。"""
    session = get_session()
    try:
        rows = session.execute(
            text("""SELECT f.file_id, f.original_name, f.file_type,
                           dc.title, rc.confidence, rc.status, rc.evidence
                    FROM relation_candidates rc
                    JOIN files f ON f.file_id = rc.target_key
                    LEFT JOIN document_contents dc ON dc.file_id = f.file_id
                    WHERE rc.cand_type = 'device_document'
                      AND rc.entity_key = :tag
                    ORDER BY rc.confidence DESC"""),
            {"tag": tag_no},
        ).fetchall()
        out = []
        for r in rows:
            out.append({
                "file_id": r[0],
                "file_name": r[1],
                "file_type": r[2],
                "title": r[3],
                "confidence": r[4],
                "status": r[5],
                "evidence": r[6],
            })
        return out
    finally:
        session.close()


def get_device_profile(tag_no: str) -> dict[str, Any]:
    """按位号返回完整设备档案。"""
    session = get_session()
    try:
        # 1. 主记录
        norm = tag_no.upper().replace("-", "").replace("_", "").replace(" ", "")
        dm = (
            session.query(DeviceMasterModel)
            .filter(
                (DeviceMasterModel.tag_no == tag_no)
                | (DeviceMasterModel.normalized_tag == norm)
            )
            .first()
        )
        if not dm:
            return {"found": False, "tag_no": tag_no}

        # 2. 出现位置
        occs = (
            session.query(DeviceOccurrenceModel)
            .filter(DeviceOccurrenceModel.device_id == dm.device_id)
            .order_by(DeviceOccurrenceModel.drawing_id)
            .all()
        )

        drawing_ids = list({o.drawing_id for o in occs})
        drawing_names = {
            d.drawing_id: d.file_name
            for d in session.query(DrawingModel.drawing_id, DrawingModel.file_name)
            .filter(DrawingModel.drawing_id.in_(drawing_ids))
            .all()
        }

        occurrences = []
        for o in occs:
            drawing_id = o.drawing_id
            file_id = _file_id_for_drawing(drawing_id)
            occurrences.append({
                "drawing_id": drawing_id,
                "file_id": file_id,
                "drawing_name": drawing_names.get(drawing_id, ""),
                "preview_path": _preview_path(drawing_id),
                "x": o.x,
                "y": o.y,
                "layer": o.layer,
                "text_content": o.text_content,
                "elevation": _elevation_for_drawing(drawing_id),
            })

        # 3. 箱单与文档
        packings = _packing_for_tag(dm.tag_no)
        documents = _documents_for_tag(dm.tag_no)
        pending_count = sum(1 for p in packings + documents if p.get("status") == "pending")

        return {
            "found": True,
            "device_id": dm.device_id,
            "tag_no": dm.tag_no,
            "normalized_tag": dm.normalized_tag,
            "name": dm.name,
            "category": dm.category,
            "subsystem_no": dm.subsystem_no,
            "drawing_count": dm.drawing_count,
            "occurrence_count": dm.occurrence_count,
            "confidence": dm.confidence,
            "occurrences": occurrences,
            "packing_lists": packings,
            "documents": documents,
            "pending_confirmations": pending_count,
        }
    finally:
        session.close()


def list_devices_by_subsystem(subsystem_no: str | None = None, limit: int = 200) -> list[dict]:
    """按子系统列出设备卡片。"""
    session = get_session()
    try:
        q = session.query(
            DeviceMasterModel.device_id,
            DeviceMasterModel.tag_no,
            DeviceMasterModel.name,
            DeviceMasterModel.category,
            DeviceMasterModel.subsystem_no,
            DeviceMasterModel.drawing_count,
        )
        if subsystem_no:
            q = q.filter(DeviceMasterModel.subsystem_no == subsystem_no)
        rows = q.order_by(DeviceMasterModel.tag_no).limit(limit).all()
        return [
            {
                "device_id": r.device_id,
                "tag_no": r.tag_no,
                "name": r.name,
                "category": r.category,
                "subsystem_no": r.subsystem_no,
                "drawing_count": r.drawing_count,
            }
            for r in rows
        ]
    finally:
        session.close()


def search_devices(query: str, limit: int = 20) -> list[dict]:
    """位号/名称模糊搜索。"""
    session = get_session()
    try:
        like = f"%{query}%"
        rows = (
            session.query(DeviceMasterModel)
            .filter(
                (DeviceMasterModel.tag_no.like(like))
                | (DeviceMasterModel.normalized_tag.like(like))
                | (DeviceMasterModel.name.like(like))
            )
            .order_by(DeviceMasterModel.occurrence_count.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "device_id": d.device_id,
                "tag_no": d.tag_no,
                "name": d.name,
                "category": d.category,
                "subsystem_no": d.subsystem_no,
                "drawing_count": d.drawing_count,
            }
            for d in rows
        ]
    finally:
        session.close()
