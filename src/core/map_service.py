"""2.5D 地图数据服务（阶段 4）。

为 map_view 提供：
- 子系统列表与统计
- 子系统内图纸列表（按位号密度排序）
- 同标高图纸列表
- 单图地图数据：底图路径、sidecar bbox、设备位号标注点
- 设备位号 → 设备档案的聚合数据
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from src.core.config import get_config
from src.database.connection import get_session
from src.core.device_profile import get_device_profile


def _preview_path(drawing_id: str) -> str | None:
    config = get_config()
    p = Path(config.kb_root) / "Preview" / f"{drawing_id}.png"
    return str(p) if p.exists() else None


def _sidecar(drawing_id: str) -> dict | None:
    config = get_config()
    p = Path(config.kb_root) / "Preview" / f"{drawing_id}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_subsystems(limit: int = 200) -> list[dict]:
    """返回有设备位号的子系统列表。"""
    session = get_session()
    try:
        rows = session.execute(text("""
            SELECT subsystem_no,
                   COUNT(DISTINCT drawing_id) as drawing_count,
                   COUNT(*) as tag_count,
                   COUNT(DISTINCT tag_no) as unique_tag_count
            FROM equipment_tags
            WHERE subsystem_no != '' AND subsystem_no IS NOT NULL
            GROUP BY subsystem_no
            ORDER BY tag_count DESC
            LIMIT :limit
        """), {"limit": limit}).fetchall()
        return [
            {
                "subsystem_no": r[0],
                "drawing_count": r[1],
                "tag_count": r[2],
                "unique_tag_count": r[3],
            }
            for r in rows
        ]
    finally:
        session.close()


def list_drawings_for_subsystem(subsystem_no: str, limit: int = 100) -> list[dict]:
    """返回某子系统下含位号的图纸，按位号密度排序。"""
    session = get_session()
    try:
        rows = session.execute(text("""
            SELECT e.drawing_id, d.file_name,
                   COUNT(*) as tag_count,
                   COUNT(DISTINCT e.tag_no) as unique_tag_count,
                   MAX(e.x) as max_x, MAX(e.y) as max_y,
                   MIN(e.x) as min_x, MIN(e.y) as min_y
            FROM equipment_tags e
            JOIN drawings d ON d.drawing_id = e.drawing_id
            WHERE e.subsystem_no = :sub
            GROUP BY e.drawing_id
            ORDER BY tag_count DESC
            LIMIT :limit
        """), {"sub": subsystem_no, "limit": limit}).fetchall()

        out = []
        for r in rows:
            did = r[0]
            sidecar = _sidecar(did)
            # 标高
            elev = session.execute(
                text("SELECT datum_elevation FROM elevations WHERE drawing_id=:did ORDER BY confidence DESC LIMIT 1"),
                {"did": did},
            ).fetchone()
            out.append({
                "drawing_id": did,
                "file_name": r[1],
                "tag_count": r[2],
                "unique_tag_count": r[3],
                "preview_path": _preview_path(did),
                "sidecar": sidecar,
                "elevation": elev[0] if elev else None,
            })
        return out
    finally:
        session.close()


def list_drawings_by_elevation(elevation: float | str, limit: int = 100) -> list[dict]:
    """返回同一标高基准下的图纸。"""
    session = get_session()
    try:
        rows = session.execute(text("""
            SELECT e.drawing_id, d.file_name,
                   COUNT(DISTINCT e.tag_no) as unique_tag_count,
                   COUNT(*) as tag_count,
                   el.datum_elevation
            FROM elevations el
            JOIN drawings d ON d.drawing_id = el.drawing_id
            LEFT JOIN equipment_tags e ON e.drawing_id = el.drawing_id
            WHERE el.datum_elevation = :elev
            GROUP BY el.drawing_id
            ORDER BY tag_count DESC
            LIMIT :limit
        """), {"elev": elevation, "limit": limit}).fetchall()
        return [
            {
                "drawing_id": r[0],
                "file_name": r[1],
                "unique_tag_count": r[2] or 0,
                "tag_count": r[3] or 0,
                "preview_path": _preview_path(r[0]),
                "elevation": r[4],
            }
            for r in rows
        ]
    finally:
        session.close()


def get_map_data(drawing_id: str) -> dict[str, Any]:
    """获取单图 2.5D 地图完整数据。"""
    session = get_session()
    try:
        # 图纸元数据
        drow = session.execute(
            text("SELECT file_name, file_type, entity_count, text_count FROM drawings WHERE drawing_id=:did"),
            {"did": drawing_id},
        ).fetchone()
        if not drow:
            return {"found": False}

        preview = _preview_path(drawing_id)
        sidecar = _sidecar(drawing_id)
        if not preview or not sidecar:
            return {"found": False, "reason": "no_preview"}

        # 位号标注点
        tag_rows = session.execute(
            text("""SELECT e.tag_no, e.x, e.y, e.height, e.layer, e.text_id,
                           p.packing_no, p.vendor, p.equip_name, rc.status
                    FROM equipment_tags e
                    LEFT JOIN (
                        SELECT entity_key, target_key, status,
                               ROW_NUMBER() OVER (PARTITION BY entity_key ORDER BY confidence DESC) as rn
                        FROM relation_candidates
                        WHERE cand_type = 'equipment_packing'
                    ) rc ON rc.entity_key = e.tag_no AND rc.rn = 1
                    LEFT JOIN (
                        SELECT packing_no,
                               MAX(vendor) as vendor,
                               MAX(equip_name) as equip_name
                        FROM packing_items
                        GROUP BY packing_no
                    ) p ON p.packing_no = rc.target_key
                    WHERE e.drawing_id = :did
                    ORDER BY e.tag_no"""),
            {"did": drawing_id},
        ).fetchall()

        tags = []
        for r in tag_rows:
            tags.append({
                "tag_no": r[0],
                "x": r[1],
                "y": r[2],
                "height": r[3] or 2.0,
                "layer": r[4],
                "text_id": r[5],
                "packing_no": r[6],
                "vendor": r[7],
                "equip_name": r[8],
                "pack_status": r[9],
            })

        # 标高
        elev = session.execute(
            text("SELECT datum_elevation, raw_text, verified FROM elevations WHERE drawing_id=:did LIMIT 1"),
            {"did": drawing_id},
        ).fetchone()

        # 同子系统其他图
        subsystem = session.execute(
            text("SELECT MAX(subsystem_no) FROM equipment_tags WHERE drawing_id=:did"),
            {"did": drawing_id},
        ).fetchone()[0]

        return {
            "found": True,
            "drawing_id": drawing_id,
            "file_name": drow[0],
            "preview_url": preview,
            "sidecar": sidecar,
            "tags": tags,
            "tag_count": len(tags),
            "elevation": {
                "datum_elevation": elev[0],
                "raw_text": elev[1],
                "verified": bool(elev[2]),
            } if elev else None,
            "subsystem_no": subsystem,
        }
    finally:
        session.close()


def get_tag_profile_on_drawing(tag_no: str, drawing_id: str) -> dict | None:
    """获取某位号在当前图纸上的具体出现 + 完整设备档案。"""
    profile = get_device_profile(tag_no)
    if not profile.get("found"):
        return None
    # 找到当前 drawing_id 的 occurrence
    occ = next((o for o in profile["occurrences"] if o["drawing_id"] == drawing_id), None)
    return {
        "device_profile": profile,
        "current_occurrence": occ,
    }
