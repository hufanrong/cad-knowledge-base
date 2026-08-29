"""Unified Agent API (Phase 6).

One stable function surface for LLM/Agent consumers to access the whole
knowledge base — CAD, documents, projects, files — without touching the
underlying schema.

Functions (mirroring the product requirement):
  search_files / search_documents / search_drawings / search_excel /
  search_projects / search_pdf / search_by_project / search_by_equipment /
  search_by_material / search_by_keyword / get_file / get_original_file /
  get_parsed_data / get_related_files / get_project_files

Principles:
- Agents read the KB's OWN archive copies (get_original_file), never the
  user's original files.
- No data is fabricated; parse failures are surfaced honestly.
"""

from __future__ import annotations

from src.core.unified_search import (
    get_file as _get_file,
    get_project_files as _get_project_files,
    get_related_files as _get_related_files,
    search_all as _search_all,
    search_by_equipment as _search_by_equipment,
    search_by_material as _search_by_material,
    search_by_project as _search_by_project,
)


# ─── search family ───────────────────────────────────────────────────

def search_files(keyword: str, limit: int = 30) -> list[dict]:
    """Search ALL files by keyword (metadata + content)."""
    return _search_all(keyword, limit=limit)


def search_documents(keyword: str, limit: int = 30) -> list[dict]:
    """Search non-CAD documents (Word/Excel/PDF/Project/...)."""
    return _search_all(
        keyword, limit=limit,
        source_types=["word", "excel", "pdf", "project", "image", "other"],
    )


def search_drawings(keyword: str, limit: int = 30) -> list[dict]:
    """Search CAD drawings only."""
    return _search_all(keyword, limit=limit, source_types=["cad"])


def search_excel(keyword: str, limit: int = 30) -> list[dict]:
    """Search Excel/CSV content."""
    return _search_all(keyword, limit=limit, source_types=["excel"])


def search_pdf(keyword: str, limit: int = 30) -> list[dict]:
    """Search PDF documents."""
    return _search_all(keyword, limit=limit, source_types=["pdf"])


def search_projects(limit: int = 100) -> list[dict]:
    """List all inferred projects."""
    from src.core.project_inference import list_projects

    return list_projects()[:limit]


def search_by_project(project_name: str, limit: int = 50) -> list[dict]:
    """All files of a project (CAD + documents together)."""
    return _search_by_project(project_name, limit=limit)


def search_by_equipment(equipment: str, limit: int = 50) -> list[dict]:
    """Files mentioning an equipment."""
    return _search_by_equipment(equipment, limit=limit)


def search_by_material(material: str, limit: int = 50) -> list[dict]:
    """Files mentioning a material (e.g. 'Q355B 60mm')."""
    return _search_by_material(material, limit=limit)


def search_by_keyword(keyword: str, limit: int = 30) -> list[dict]:
    """Generic keyword search (alias of search_files)."""
    return search_files(keyword, limit=limit)


# ─── get family ──────────────────────────────────────────────────────

def get_file(file_id: str) -> dict | None:
    """Get a file record by UUID (metadata, not content)."""
    return _get_file(file_id)


def get_original_file(file_id: str) -> dict:
    """Return the KB archive copy info for a file_id.

    Agents MUST use this (the KB copy), never the user's original path.
    Returns: {file_id, file_name, archive_path, original_path,
    file_type, source_type, parse_status} or {error}.
    """
    rec = _get_file(file_id)
    if not rec:
        return {"error": f"file_id 不存在: {file_id}"}
    return {
        "file_id": rec.get("file_id"),
        "file_name": rec.get("file_name"),
        "archive_path": rec.get("archive_path"),   # KB-owned copy
        "original_path": rec.get("original_path"),  # reference only
        "file_type": rec.get("file_type"),
        "source_type": rec.get("source_type"),
        "parse_status": rec.get("parse_status"),
        "file_size": rec.get("file_size"),
    }


def get_parsed_data(file_id: str) -> dict:
    """Return parsed content of a document (content + markdown paths)."""
    from src.database.connection import get_session
    from src.database.models import DocumentContentModel

    session = get_session()
    try:
        rec = (
            session.query(DocumentContentModel)
            .filter(DocumentContentModel.file_id == file_id)
            .first()
        )
        if not rec:
            return {"error": f"未找到解析数据: {file_id}"}
        return {
            "file_id": rec.file_id,
            "source_type": rec.source_type,
            "title": rec.title,
            "source": rec.source,              # text | ocr
            "confidence": rec.confidence,
            "content": rec.content,
            "json_path": rec.json_path,
            "md_path": rec.md_path,
            "txt_path": rec.txt_path,
        }
    finally:
        session.close()


def get_related_files(file_id: str, limit: int = 50) -> list[dict]:
    """Files related to file_id (same project / same equipment / ...)."""
    return _get_related_files(file_id, limit=limit)


def get_project_files(project_id: str, limit: int = 50) -> list[dict]:
    """All files of a project by project_id."""
    return _get_project_files(project_id, limit=limit)


# ─── RAG / QA ────────────────────────────────────────────────────────

def ask_knowledge(query: str, top_k: int = 8) -> dict:
    """Cross-format QA (CAD + documents)."""
    from src.qa.qa_service import ask_question

    answer = ask_question(query, top_k=top_k)
    return answer.model_dump()
