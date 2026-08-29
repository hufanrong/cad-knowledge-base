"""设备档案批量导出服务（阶段6）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.styles import Font, PatternFill
from sqlalchemy import text

from src.database.connection import get_session


def _fetch_all() -> list[dict[str, Any]]:
    """聚合 device_master + 出现图纸 + 箱单候选。"""
    session = get_session()
    try:
        devices = session.execute(text(
            "SELECT device_id, tag_no, name, category, subsystem_no, "
            "drawing_count, occurrence_count, confidence "
            "FROM device_master ORDER BY subsystem_no, tag_no"
        )).fetchall()

        occurrences = session.execute(text(
            "SELECT doc.device_id, d.file_name "
            "FROM device_occurrences doc "
            "JOIN drawings d ON d.drawing_id = doc.drawing_id"
        )).fetchall()
        occ_map: dict[str, list[str]] = {}
        for device_id, fn in occurrences:
            occ_map.setdefault(device_id, []).append(fn)

        packings = session.execute(text(
            "SELECT dm.device_id, pi.packing_no, pi.equip_name, pi.vendor, rc.status "
            "FROM device_master dm "
            "JOIN relation_candidates rc ON rc.entity_key = dm.tag_no "
            "JOIN packing_items pi ON pi.packing_no = rc.target_key "
            "WHERE rc.cand_type = 'equipment_packing'"
        )).fetchall()
        pack_map: dict[str, list[dict]] = {}
        for device_id, pno, ename, vendor, status in packings:
            pack_map.setdefault(device_id, []).append({
                "packing_no": pno,
                "equip_name": ename,
                "vendor": vendor,
                "status": status,
            })

        out = []
        for did, tag, name, cat, sub, dc, oc, conf in devices:
            packs = pack_map.get(did, [])
            confirmed = sum(1 for p in packs if p["status"] == "confirmed")
            pending = sum(1 for p in packs if p["status"] == "pending")
            hint = "; ".join(
                f"{p['packing_no']}:{p['equip_name']}:{p['vendor']}"
                for p in packs[:5]
            )
            out.append({
                "tag_no": tag,
                "name": name or "",
                "category": cat or "",
                "subsystem_no": sub or "",
                "drawing_count": dc,
                "occurrence_count": oc,
                "confidence": conf or 0.0,
                "drawings": "; ".join(sorted(set(occ_map.get(did, [])))),
                "confirmed_packing": confirmed,
                "pending_packing": pending,
                "packing_hints": hint,
            })
        return out
    finally:
        session.close()


def export_device_profiles(output_path: str | Path, subsystem_no: str | None = None) -> Path:
    """导出设备档案到 Excel。"""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "设备档案"

    headers = [
        "位号", "设备名称", "类别", "子系统", "跨图数", "标注点数",
        "置信度", "出现图纸", "已确认箱单", "待确认箱单", "箱单候选",
    ]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9E1F2")

    rows = _fetch_all()
    if subsystem_no:
        rows = [r for r in rows if r.get("subsystem_no") == subsystem_no]

    for r in rows:
        ws.append([
            r["tag_no"],
            r["name"],
            r["category"],
            r["subsystem_no"],
            r["drawing_count"],
            r["occurrence_count"],
            round(r["confidence"], 2),
            r["drawings"],
            r["confirmed_packing"],
            r["pending_packing"],
            r["packing_hints"],
        ])

    for col in ws.columns:
        max_len = 0
        col_letter = col[0].column_letter
        for cell in col:
            try:
                max_len = max(max_len, len(str(cell.value)))
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = min(max_len + 2, 60)

    wb.save(str(out))
    return out
