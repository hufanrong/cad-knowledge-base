"""Engineering document generators (acceptance records, hoisting plans, schedules).

These generators read evidence from the CAD knowledge base and combine it with
user-supplied site data to produce standardized Word/Excel deliverables.

Design principles:
- Evidence-based: never fabricate numbers; clearly mark missing fields.
- Template-driven: default templates are embedded; user templates can override.
- Read-only on the database.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from src.core.agent_query import agent_query
from src.core.device_profile import get_device_profile
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.document_generator")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SiteData:
    """User-supplied field measurements or constraints."""

    actual_values: dict[str, Any] = None
    inspectors: str = ""
    inspection_date: str = ""
    remarks: str = ""
    crane_model: str = ""
    crane_radius: str = ""
    boom_length: str = ""
    lifting_weight: str = ""
    weather: str = ""

    def __post_init__(self):
        if self.actual_values is None:
            self.actual_values = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe(value: Any, default: str = "—") -> str:
    return str(value) if value is not None else default


def _get_device_summary(tag_no: str) -> dict[str, Any]:
    """Fetch a concise device profile for document templates."""
    profile = get_device_profile(tag_no)
    if not profile.get("found"):
        return {"found": False, "tag_no": tag_no}

    first_occ = profile.get("occurrences", [{}])[0]
    elevation = first_occ.get("elevation", {})

    # Try to infer equipment name from packing candidates
    packings = profile.get("packing_candidates", [])
    equip_name = ""
    vendor = ""
    if packings:
        equip_name = packings[0].get("equip_name", "")
        vendor = packings[0].get("vendor", "")

    return {
        "found": True,
        "tag_no": tag_no,
        "name": equip_name or profile.get("name", ""),
        "category": profile.get("category", ""),
        "vendor": vendor,
        "subsystem": profile.get("subsystem_no", ""),
        "drawing_count": profile.get("drawing_count", 0),
        "occurrence_count": profile.get("occurrence_count", 0),
        "elevation": elevation.get("datum_elevation", ""),
        "drawings": [o.get("drawing_name", "") for o in profile.get("occurrences", [])[:5]],
        "packings": packings[:3],
    }


def _get_agent_evidence(query: str) -> dict[str, Any]:
    """Run agent query and return a flattened evidence summary."""
    result = agent_query(query)
    evidence = {
        "tags": result.parsed.tags,
        "subsystems": result.parsed.subsystems,
        "intent": result.parsed.intent,
        "gaps": result.gaps,
        "drawings": [],
        "devices": [],
    }
    for ev in result.evidence:
        if ev.get("type") == "subsystem_drawings":
            evidence["drawings"].extend(ev.get("drawings", []))
        elif ev.get("type") == "device_profile":
            evidence["devices"].append(ev.get("data", {}))
    return evidence


# ---------------------------------------------------------------------------
# Excel styling helpers
# ---------------------------------------------------------------------------

def _set_title(ws, row: int, col: int, value: str, bold: bool = True):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = Font(bold=bold, size=12 if bold else 11)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _border_all(ws, min_row: int, max_row: int, min_col: int, max_col: int):
    thin = Side(style="thin", color="000000")
    for r in range(min_row, max_row + 1):
        for c in range(min_col, max_col + 1):
            ws.cell(row=r, column=c).border = Border(left=thin, right=thin, top=thin, bottom=thin)


# ---------------------------------------------------------------------------
# 1. Acceptance record (Excel)
# ---------------------------------------------------------------------------

def generate_acceptance_record(
    tag_no: str,
    site_data: SiteData | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Generate an equipment installation acceptance record Excel.

    Args:
        tag_no: Equipment tag number, e.g. CF0204ME01.
        site_data: Optional field measurements and inspector info.
        output_path: Where to save. Defaults to Temp/<tag>_acceptance_<date>.xlsx.

    Returns:
        Path to the generated file.
    """
    site_data = site_data or SiteData()
    dev = _get_device_summary(tag_no)

    if output_path is None:
        from src.core.config import get_config
        out_dir = get_config().temp_dir / "generated"
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / f"{tag_no}_acceptance_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    output_path = Path(output_path)

    wb = Workbook()
    ws = wb.active
    ws.title = "验收记录"

    # Title
    ws.merge_cells("A1:F1")
    _set_title(ws, 1, 1, f"{tag_no} 设备安装验收记录")
    ws.row_dimensions[1].height = 30

    # Meta info
    ws.cell(row=3, column=1, value="设备位号")
    ws.cell(row=3, column=2, value=_safe(dev.get("tag_no")))
    ws.cell(row=3, column=3, value="设备名称")
    ws.cell(row=3, column=4, value=_safe(dev.get("name")))
    ws.cell(row=3, column=5, value="类别")
    ws.cell(row=3, column=6, value=_safe(dev.get("category")))

    ws.cell(row=4, column=1, value="厂家/供应商")
    ws.cell(row=4, column=2, value=_safe(dev.get("vendor")))
    ws.cell(row=4, column=3, value="子系统")
    ws.cell(row=4, column=4, value=_safe(dev.get("subsystem")))
    ws.cell(row=4, column=5, value="标高")
    ws.cell(row=4, column=6, value=_safe(dev.get("elevation")))

    ws.cell(row=5, column=1, value="图纸依据")
    ws.merge_cells("B5:F5")
    ws.cell(row=5, column=2, value="; ".join(dev.get("drawings", [])) or "—")

    ws.cell(row=6, column=1, value="验收日期")
    ws.cell(row=6, column=2, value=site_data.inspection_date or datetime.now().strftime("%Y-%m-%d"))
    ws.cell(row=6, column=3, value="验收人员")
    ws.cell(row=6, column=4, value=_safe(site_data.inspectors))

    # Inspection items
    ws.cell(row=8, column=1, value="序号")
    ws.cell(row=8, column=2, value="检查项目")
    ws.cell(row=8, column=3, value="标准要求")
    ws.cell(row=8, column=4, value="实测数据")
    ws.cell(row=8, column=5, value="结论")
    ws.cell(row=8, column=6, value="备注")

    items = [
        ("设备基础尺寸", "符合设计图纸", "基础长/宽/高"),
        ("基础标高", "符合设计图纸", "绝对/相对标高"),
        ("地脚螺栓", "规格、数量、外露长度符合要求", "螺栓规格/间距"),
        ("设备就位", "中心线、标高、水平度符合要求", "水平度/中心偏差"),
        ("水平度", "≤0.1mm/m 或设计要求", "实测值"),
        ("联轴器对中", "径向/轴向偏差符合规范", "径向/轴向偏差"),
        ("电气接线", "相序、接地正确", "绝缘电阻/接地电阻"),
        ("润滑/冷却系统", "油路/水路畅通无泄漏", "压力/流量"),
        ("安全防护", "防护罩、护栏齐全", "目视检查"),
        ("单机试车", "运行平稳、无异常振动噪声", "电流/振动/温升"),
    ]

    for i, (item, standard, hint) in enumerate(items, start=1):
        r = 8 + i
        ws.cell(row=r, column=1, value=i)
        ws.cell(row=r, column=2, value=item)
        ws.cell(row=r, column=3, value=standard)
        ws.cell(row=r, column=4, value=site_data.actual_values.get(item, ""))
        ws.cell(row=r, column=5, value=site_data.actual_values.get(f"{item}_结论", ""))
        ws.cell(row=r, column=6, value=hint)

    # Sign-off
    r = 8 + len(items) + 2
    ws.cell(row=r, column=1, value="综合结论")
    ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=6)
    ws.cell(row=r, column=2, value=site_data.remarks or "待填写")

    r += 2
    ws.cell(row=r, column=1, value="施工单位")
    ws.cell(row=r, column=3, value="监理单位")
    ws.cell(row=r, column=5, value="建设单位")

    # Formatting
    _border_all(ws, 3, 6 + len(items) + 4, 1, 6)
    for row in ws.iter_rows(min_row=8, max_row=8 + len(items), min_col=1, max_col=6):
        for cell in row:
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 28
    ws.column_dimensions["D"].width = 20
    ws.column_dimensions["E"].width = 12
    ws.column_dimensions["F"].width = 20

    wb.save(output_path)
    logger.info(f"验收记录已生成: {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# 2. Hoisting plan (Word)
# ---------------------------------------------------------------------------

def generate_hoisting_plan(
    tag_no: str,
    site_data: SiteData | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Generate a hoisting plan Word document.

    Args:
        tag_no: Equipment tag number.
        site_data: Crane selection and site constraints.
        output_path: Where to save. Defaults to Temp/<tag>_hoisting_<date>.docx.

    Returns:
        Path to the generated file.
    """
    site_data = site_data or SiteData()
    dev = _get_device_summary(tag_no)

    if output_path is None:
        from src.core.config import get_config
        out_dir = get_config().temp_dir / "generated"
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / f"{tag_no}_hoisting_{datetime.now():%Y%m%d_%H%M%S}.docx"
    output_path = Path(output_path)

    from docx import Document
    from docx.shared import Inches, Pt

    doc = Document()
    doc.add_heading(f"{tag_no} 设备吊装方案", level=0).alignment = 1

    # 1. Project overview
    doc.add_heading("一、工程概况", level=1)
    doc.add_paragraph(
        f"本方案针对子系统 {dev.get('subsystem', '—')} 设备 {tag_no} "
        f"（{dev.get('name') or '设备名称待补充'}）的吊装作业编制。"
        f"该设备在资料库中共出现 {dev.get('occurrence_count', 0)} 次，"
        f"关联图纸 {dev.get('drawing_count', 0)} 张。"
    )

    # 2. Equipment parameters
    doc.add_heading("二、设备参数", level=1)
    table = doc.add_table(rows=1, cols=2)
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    hdr[0].text = "项目"
    hdr[1].text = "内容"
    params = [
        ("设备位号", tag_no),
        ("设备名称", dev.get("name") or "待补充"),
        ("设备类别", dev.get("category") or "待补充"),
        ("厂家/供应商", dev.get("vendor") or "待补充"),
        ("子系统", dev.get("subsystem") or "待补充"),
        ("安装标高", dev.get("elevation") or "待补充"),
        ("重量", site_data.actual_values.get("重量", "待补充")),
        ("外形尺寸", site_data.actual_values.get("外形尺寸", "待补充")),
        ("重心位置", site_data.actual_values.get("重心位置", "待补充")),
    ]
    for key, val in params:
        row = table.add_row().cells
        row[0].text = key
        row[1].text = str(val)

    # 3. Crane selection
    doc.add_heading("三、起重机选型", level=1)
    crane_table = doc.add_table(rows=1, cols=2)
    crane_table.style = "Light Grid Accent 1"
    hdr = crane_table.rows[0].cells
    hdr[0].text = "项目"
    hdr[1].text = "参数"
    for key, val in [
        ("起重机型号", site_data.crane_model or "待补充"),
        ("最小吊装半径", site_data.crane_radius or "待补充"),
        ("主臂长度", site_data.boom_length or "待补充"),
        ("额定起重量", site_data.lifting_weight or "待补充"),
        ("天气条件", site_data.weather or "待补充"),
    ]:
        row = crane_table.add_row().cells
        row[0].text = key
        row[1].text = str(val)

    # 4. Drawings / evidence
    doc.add_heading("四、图纸依据", level=1)
    if dev.get("drawings"):
        for d in dev["drawings"]:
            doc.add_paragraph(d, style="List Bullet")
    else:
        doc.add_paragraph("待补充相关图纸依据。")

    # 5. Gaps
    evidence = _get_agent_evidence(f"{dev.get('subsystem', '')} 子系统 {tag_no} 吊装方案")
    if evidence.get("gaps"):
        doc.add_heading("五、待补充资料", level=1)
        for g in evidence["gaps"]:
            doc.add_paragraph(g, style="List Bullet")

    # 6. Safety
    doc.add_heading("六、安全措施", level=1)
    for item in [
        "吊装前确认起重机支腿稳固、站位场地承载力满足要求。",
        "吊装区域设置警戒，非作业人员不得进入。",
        "吊索具经检查合格，吊点按设备图或厂家要求设置。",
        "六级以上大风、大雨、大雾天气禁止吊装作业。",
        "设专人指挥，指挥信号清晰统一。",
    ]:
        doc.add_paragraph(item, style="List Bullet")

    doc.add_paragraph("\n编制：__________    审核：__________    批准：__________")
    doc.save(output_path)
    logger.info(f"吊装方案已生成: {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# 3. Schedule (weekly / monthly)
# ---------------------------------------------------------------------------

def generate_schedule(
    plan_type: str,
    items: list[dict[str, Any]] | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Generate a weekly/monthly construction schedule Excel.

    Args:
        plan_type: "weekly" or "monthly".
        items: List of {"task", "subsystem", "start", "finish", "owner", "status"}.
        output_path: Where to save.

    Returns:
        Path to the generated file.
    """
    if plan_type not in ("weekly", "monthly"):
        raise ValueError("plan_type must be 'weekly' or 'monthly'")

    if output_path is None:
        from src.core.config import get_config
        out_dir = get_config().temp_dir / "generated"
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / f"{plan_type}_plan_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    output_path = Path(output_path)

    wb = Workbook()
    ws = wb.active
    ws.title = "施工计划"

    title = "周施工计划" if plan_type == "weekly" else "月施工计划"
    ws.merge_cells("A1:F1")
    _set_title(ws, 1, 1, title)
    ws.row_dimensions[1].height = 28

    # Header
    headers = ["序号", "作业项目", "子系统/区域", "计划开始", "计划完成", "责任人", "状态/备注"]
    for c, h in enumerate(headers, start=1):
        ws.cell(row=3, column=c, value=h)
        ws.cell(row=3, column=c).font = Font(bold=True)
        ws.cell(row=3, column=c).alignment = Alignment(horizontal="center", vertical="center")

    # Items
    items = items or []
    if not items:
        # Default placeholder
        items = [
            {"task": "（示例）设备基础验收", "subsystem": "", "start": "", "finish": "", "owner": "", "status": ""},
            {"task": "（示例）设备吊装就位", "subsystem": "", "start": "", "finish": "", "owner": "", "status": ""},
            {"task": "（示例）单机试车", "subsystem": "", "start": "", "finish": "", "owner": "", "status": ""},
        ]

    for i, it in enumerate(items, start=1):
        r = 3 + i
        ws.cell(row=r, column=1, value=i)
        ws.cell(row=r, column=2, value=it.get("task", ""))
        ws.cell(row=r, column=3, value=it.get("subsystem", ""))
        ws.cell(row=r, column=4, value=it.get("start", ""))
        ws.cell(row=r, column=5, value=it.get("finish", ""))
        ws.cell(row=r, column=6, value=it.get("owner", ""))
        ws.cell(row=r, column=7, value=it.get("status", ""))

    _border_all(ws, 3, 3 + len(items), 1, 7)
    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 35
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 14
    ws.column_dimensions["E"].width = 14
    ws.column_dimensions["F"].width = 12
    ws.column_dimensions["G"].width = 18

    wb.save(output_path)
    logger.info(f"施工计划已生成: {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# High-level dispatcher
# ---------------------------------------------------------------------------

def generate_document(
    doc_type: str,
    tag_no: str | None = None,
    site_data: SiteData | None = None,
    items: list[dict[str, Any]] | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Dispatch to the right generator."""
    if doc_type == "acceptance":
        if not tag_no:
            raise ValueError("acceptance requires tag_no")
        return generate_acceptance_record(tag_no, site_data=site_data, output_path=output_path)
    if doc_type == "hoisting":
        if not tag_no:
            raise ValueError("hoisting requires tag_no")
        return generate_hoisting_plan(tag_no, site_data=site_data, output_path=output_path)
    if doc_type in ("weekly", "monthly"):
        return generate_schedule(doc_type, items=items, output_path=output_path)
    raise ValueError(f"Unknown doc_type: {doc_type}")
