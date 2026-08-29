"""Project inference (Phase 5).

Auto-infer a project name from a file, ALWAYS with a confidence score.
Sources (priority order):
  1. User-specified (highest confidence, 1.0)
  2. CAD title block fields (图纸名称/项目名称)
  3. Word title / Excel sheet names / PDF title
  4. Filename pattern (e.g. "205冷却窑..." project prefix)
  5. Original path keywords

If confidence would be too low -> project stays None (never guess).
"""

from __future__ import annotations

import re
from pathlib import Path

from src.database.connection import get_session
from src.database.models import ProjectModel
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.project_inference")

# 常见项目命名模式：数字前缀 + 项目名，如 "205冷却窑"、"0205 熟料粉磨装置"
# 用于从文件名/路径提取项目名。
PROJECT_PATTERN = re.compile(
    r"(?P<name>(?:[0-9]{2,4}\s*[一-龥A-Za-z0-9\-（）()·]+)"
    r"|(?:[一-龥A-Za-z0-9]{2,}[项]目)"
    r"|(?:[一-龥A-Za-z0-9]{2,}(?:装置|系统|车间|厂房|工段|工程)))"
)

# 无意义片段（不作为项目名）
STOP_WORDS = {
    "设计图纸", "施工图", "图纸", "资料", "文件", "备份", "最终版",
    "新建文件夹", "临时", "项目", "工程", "扫描", "图片",
    "工艺图", "结构图", "平面图", "布置图", "系统图", "原理图",
}

# 文档类型后缀（从文件名中剥离，得到项目核心名）
DOC_SUFFIXES = [
    "安装方案", "技术协议", "施工进度", "施工方案", "设计方案", "设计说明",
    "设备清单", "材料表", "工艺图", "结构图", "平面图", "布置图",
    "系统图", "原理图", "大样图", "详图", "总图", "剖面图", "立面图",
    "非标图", "配管图", "流程图", "进度计划", "检验记录", "验收记录",
    "说明书", "操作规程", "维护手册", "预算书", "招标文件", "合同",
]


def _strip_doc_suffix(name: str) -> str:
    """Strip document-type suffix + year markers to get project core."""
    name = name.strip()
    changed = True
    while changed and name:
        changed = False
        for suf in DOC_SUFFIXES:
            if name.endswith(suf):
                name = name[: -len(suf)].strip()
                changed = True
                break
        for marker in ("（202", "(202", "（20", "(20", " -R", "-R0",
                       " R0", "-R1", "-R2", "-R3"):
            idx = name.find(marker)
            if idx > 0:
                name = name[:idx].strip()
                changed = True
                break
        # 清理尾部残留分隔符（-、_、（ 等）
        if name.endswith(("-", "_", "（", "(", "、", "·")):
            name = name[:-1].strip()
            changed = True
    return name


def _is_meaningless_name(name: str) -> bool:
    """Reject names that are clearly not project names."""
    if not name:
        return True
    if re.fullmatch(r"\d{2,4}", name):            # 纯数字
        return True
    if re.fullmatch(r"\d{6,8}", name):            # 纯日期数字
        return True
    if re.match(r"^(IMG|DSC|PIC|photo|微信图片|截图|Screenshot|照片|图|扫描)",
                name, re.IGNORECASE):
        return True
    if len(name) < 2:
        return True
    return False


def infer_project_from_file(
    file_name: str,
    file_path: str = "",
    title_block: dict | None = None,
    doc_title: str = "",
) -> dict | None:
    """Infer project for a file.

    Returns: {name, confidence, source} or None (don't guess).
    """
    candidates: list[tuple[str, float, str]] = []
    stem = Path(file_name).stem

    # 1. Title block (CAD) — strongest signal
    if title_block:
        for key in ("项目名称", "项目", "工程名称"):
            val = title_block.get(key) or title_block.get(key.lower(), "")
            val = str(val).strip()
            if val and val not in STOP_WORDS and len(val) <= 40:
                candidates.append((val, 0.95, "title_block"))

    # 2. Filename project pattern (e.g. "205冷却窑安装方案" -> "205冷却窑")
    m = PROJECT_PATTERN.search(stem)
    if m:
        name = _strip_doc_suffix(m.group("name").strip())
        if (name and not _is_meaningless_name(name)
                and name not in STOP_WORDS and len(name) <= 40):
            candidates.append((name, 0.85, "filename"))

    # 3. Document title (Word/Excel/PDF) — only if filename gave nothing
    if doc_title:
        t = _strip_doc_suffix(doc_title.strip())
        if (t and not _is_meaningless_name(t)
                and t not in STOP_WORDS and len(t) <= 40
                and not any(c[0] == t for c in candidates)):
            candidates.append((t, 0.75, "doc_title"))

    # 4. Path keywords (last meaningful folder)
    if file_path:
        parts = [p for p in Path(file_path).parts if p not in STOP_WORDS]
        for part in reversed(parts):
            if part and part != Path(file_path).name:
                candidates.append((part, 0.5, "path"))
                break

    if not candidates:
        return None

    # Pick highest confidence
    candidates.sort(key=lambda c: c[1], reverse=True)
    name, conf, source = candidates[0]
    if conf < 0.5:
        return None  # too weak -> don't guess
    return {"name": name, "confidence": round(conf, 2), "source": source}


def assign_project_to_file(
    file_id: str,
    file_name: str,
    file_path: str = "",
    title_block: dict | None = None,
    doc_title: str = "",
) -> dict | None:
    """Infer + create/assign project for a registered file."""
    from src.core.file_registry import FileRegistry

    inferred = infer_project_from_file(
        file_name, file_path, title_block, doc_title)
    if not inferred:
        return None

    reg = FileRegistry()
    try:
        proj = reg.get_or_create_project(
            inferred["name"],
            confidence=inferred["confidence"],
            source=inferred["source"],
        )
        reg.assign_project(file_id, proj.project_id)
        return inferred
    finally:
        reg.close()


def list_projects() -> list[dict]:
    """List all inferred projects with file counts.

    只返回挂接 ≥2 个文件的项目。单工程资料库中，project_inference
    会从 PDF 标题/目录名推断出大量只挂 1 个文件的噪音"项目"
    （如"000消音器（竣）""供应商门户"），在此过滤而非清洗数据表，
    原始记录保留可审计。
    """
    from src.database.connection import get_session
    from src.database.models import FileModel
    from sqlalchemy import func

    session = get_session()
    try:
        rows = (
            session.query(
                ProjectModel.project_id,
                ProjectModel.name,
                ProjectModel.confidence,
                ProjectModel.source,
                func.count(FileModel.file_id).label("file_count"),
            )
            .outerjoin(FileModel, FileModel.project_id == ProjectModel.project_id)
            .group_by(ProjectModel.project_id)
            .having(func.count(FileModel.file_id) >= 2)
            .order_by(func.count(FileModel.file_id).desc())
            .all()
        )
        return [
            {
                "project_id": r.project_id,
                "name": r.name,
                "confidence": r.confidence,
                "source": r.source,
                "file_count": r.file_count,
            }
            for r in rows
        ]
    finally:
        session.close()
