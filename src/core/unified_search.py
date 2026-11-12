"""Unified multi-format search (Phase 5).

Searches across ALL file types in one query:
- CAD: drawings (name/notes) + texts (entities) + attributes
- Documents: document_contents (Word/Excel/PDF/... content) via FTS5
- Files: registry metadata (name, tags, path)

Also provides project/equipment/material-oriented lookups.
"""

from __future__ import annotations

import json

from sqlalchemy import text

from src.core.fts_query import build_match
from src.database.connection import get_session
from src.database.models import (
    DocumentContentModel,
    DrawingModel,
    FileModel,
    ProjectModel,
)
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.unified_search")


def search_all(
    query: str,
    limit: int = 30,
    source_types: list[str] | None = None,
    project_id: str = "",
) -> list[dict]:
    """Search everything: CAD + documents + file metadata.

    Args:
        query: Keyword(s) to search.
        limit: Max results.
        source_types: Optional filter (cad/word/excel/pdf/project/image/other).
        project_id: 工程隔离（P1）——非空时只返回 平台级(空/None) + 本工程 资料；
            空串 = 平台级查询，不过滤。

    Returns:
        List of results: {file_id, file_name, source_type, match_type,
        snippet, drawing_id, original_path, archive_path, score}
    """
    session = get_session()
    try:
        results: list[dict] = []
        q = f'"{query}"' if " " in query.strip() else query.strip()

        # 1. Documents FTS
        if not source_types or any(t in source_types for t in
                                   ("word", "excel", "pdf", "project",
                                    "image", "other")):
            doc_rows = _fts_documents(session, q, limit, project_id)
            results.extend(doc_rows)

        # 2. CAD texts FTS
        if not source_types or "cad" in source_types:
            cad_rows = _fts_cad(session, q, limit, project_id)
            results.extend(cad_rows)

        # 3. File metadata (filename/tags) — respect source filter
        meta_rows = _fts_files(session, query, limit, source_types, project_id)
        results.extend(meta_rows)

        # Dedup by file identity, keep best score first
        seen = {}
        for r in results:
            key = r.get("file_id") or (r.get("drawing_id"), r["source_type"])
            if key in seen:
                continue
            seen[key] = r
        ordered = sorted(seen.values(), key=lambda r: r.get("score", 0),
                         reverse=True)
        return ordered[:limit]
    finally:
        session.close()


def search_by_project(project_name: str, limit: int = 50) -> list[dict]:
    """Find all files belonging to a project (by name)."""
    session = get_session()
    try:
        proj = (
            session.query(ProjectModel)
            .filter(ProjectModel.name == project_name)
            .first()
        )
        if not proj:
            return []
        rows = (
            session.query(FileModel)
            .filter(FileModel.project_id == proj.project_id)
            .limit(limit)
            .all()
        )
        out = []
        for r in rows:
            d = _file_to_dict(r)
            d["project"] = proj.name
            d["match_type"] = "project"
            d["score"] = proj.confidence
            out.append(d)
        return out
    finally:
        session.close()


def search_by_equipment(equipment: str, limit: int = 50) -> list[dict]:
    """Find files mentioning an equipment (CAD equipment table +
    document content)."""
    return search_all(equipment, limit=limit)


def search_by_material(material: str, limit: int = 50) -> list[dict]:
    """Find files mentioning a material (e.g. 'Q355B 60mm')."""
    return search_all(material, limit=limit)


def get_file(file_id: str) -> dict | None:
    """Get a single file record by UUID."""
    session = get_session()
    try:
        r = session.query(FileModel).filter(FileModel.file_id == file_id).first()
        return _file_to_dict(r) if r else None
    finally:
        session.close()


def get_related_files(file_id: str, limit: int = 50) -> list[dict]:
    """Files related to a given file_id (via file_relations).

    belongs_to_subsystem 关系的 file_b 是子系统名（如"0201 回转窑尾装置"）
    而非 file_id，需反查同子系统全部 file_a；其他关系类型按 id 直连。
    """
    from src.core.file_registry import FileRegistry

    reg = FileRegistry()
    try:
        rels = reg.list_relations(file_id)
        ids = set()
        session = get_session()
        try:
            for rel in rels:
                if rel.get("relation_type") == "belongs_to_subsystem":
                    rows = session.execute(
                        text(
                            "SELECT DISTINCT file_a FROM file_relations "
                            "WHERE relation_type='belongs_to_subsystem' "
                            "AND file_b=:b"
                        ),
                        {"b": rel["file_b"]},
                    ).fetchall()
                    ids.update(r[0] for r in rows)
                else:
                    ids.add(rel["file_a"])
                    ids.add(rel["file_b"])
            ids.discard(file_id)
            out = []
            for fid in list(ids)[:limit]:
                r = session.query(FileModel).filter(
                    FileModel.file_id == fid).first()
                if r:
                    d = _file_to_dict(r)
                    d["match_type"] = "related"
                    out.append(d)
        finally:
            session.close()
        return out
    finally:
        reg.close()


def get_project_files(project_id: str, limit: int = 50) -> list[dict]:
    """All files for a project_id."""
    session = get_session()
    try:
        rows = (
            session.query(FileModel)
            .filter(FileModel.project_id == project_id)
            .limit(limit)
            .all()
        )
        return [_file_to_dict(r) for r in rows]
    finally:
        session.close()


# ── internal FTS helpers ─────────────────────────────────────────────

def _fts_documents(session, q: str, limit: int,
                   project_id: str = "") -> list[dict]:
    match = build_match(q)
    if not match:
        return []
    try:
        sql = """
                SELECT d.file_id, d.title, d.content, d.source_type,
                       d.source, d.confidence,
                       f.original_name, f.original_path, f.archive_path,
                       f.drawing_id, f.file_size, f.import_time,
                       bm25(documents_fts) AS score
                FROM documents_fts
                JOIN document_contents d
                  ON documents_fts.file_id = d.file_id
                LEFT JOIN files f ON d.file_id = f.file_id
                WHERE documents_fts MATCH :q
            """
        params: dict = {"q": match, "lim": limit}
        if project_id:
            sql += (" AND (f.project_id = :pid OR f.project_id = '' "
                    "OR f.project_id IS NULL)")
            params["pid"] = project_id
        sql += " ORDER BY score LIMIT :lim"
        rows = session.execute(text(sql), params)
        out = []
        for r in rows:
            snippet = _make_snippet(r.content, q)
            out.append({
                "file_id": r.file_id,
                "file_name": r.original_name or r.title,
                "source_type": r.source_type,
                "match_type": "document",
                "snippet": snippet,
                "title": r.title,
                "doc_source": r.source,
                "confidence": r.confidence,
                "original_path": r.original_path,
                "archive_path": r.archive_path,
                "drawing_id": r.drawing_id,
                "file_size": r.file_size,
                "import_time": str(r.import_time) if r.import_time else None,
                "score": -float(r.score or 0),
            })
        return out
    except Exception as e:
        logger.warning(f"documents_fts 搜索失败: {e}")
        return []


def _fts_cad(session, q: str, limit: int,
             project_id: str = "") -> list[dict]:
    out = []
    match = build_match(q)
    if not match:
        return out
    try:
        sql = """
                SELECT t.text_content, t.drawing_id,
                       d.file_name, d.file_path, d.file_hash
                FROM texts_fts
                JOIN texts t ON texts_fts.entity_id = t.entity_id
                JOIN drawings d ON t.drawing_id = d.drawing_id
                WHERE texts_fts MATCH :q
            """
        params: dict = {"q": match, "lim": limit}
        if project_id:
            sql += (" AND EXISTS (SELECT 1 FROM files fl "
                    "WHERE fl.drawing_id = d.drawing_id "
                    "AND (fl.project_id = :pid OR fl.project_id = '' "
                    "OR fl.project_id IS NULL))")
            params["pid"] = project_id
        sql += " ORDER BY bm25(texts_fts) LIMIT :lim"
        rows = session.execute(text(sql), params)
        for r in rows:
            out.append({
                "file_id": None,
                "file_name": r.file_name,
                "source_type": "cad",
                "match_type": "cad_text",
                "snippet": r.text_content[:200],
                "drawing_id": r.drawing_id,
                "original_path": r.file_path,
                "score": 0.9,
            })
    except Exception as e:
        logger.warning(f"texts_fts 搜索失败: {e}")

    # Drawing filename matches
    try:
        sql = """
                SELECT d.file_name, d.drawing_id, d.file_path, d.file_hash
                FROM drawings d
                WHERE d.file_name LIKE :kw
            """
        params = {"kw": f"%{q}%", "lim": limit}
        if project_id:
            sql += (" AND EXISTS (SELECT 1 FROM files fl "
                    "WHERE fl.drawing_id = d.drawing_id "
                    "AND (fl.project_id = :pid OR fl.project_id = '' "
                    "OR fl.project_id IS NULL))")
            params["pid"] = project_id
        sql += " LIMIT :lim"
        rows = session.execute(text(sql), params)
        for r in rows:
            out.append({
                "file_id": None,
                "file_name": r.file_name,
                "source_type": "cad",
                "match_type": "cad_filename",
                "snippet": "",
                "drawing_id": r.drawing_id,
                "original_path": r.file_path,
                "score": 0.8,
            })
    except Exception as e:
        logger.warning(f"drawings 搜索失败: {e}")
    return out


def _fts_files(session, query: str, limit: int,
               source_types: list[str] | None = None,
               project_id: str = "") -> list[dict]:
    """File registry metadata matches (filename/tags/path)."""
    kw = f"%{query}%"
    try:
        q = session.query(FileModel).filter(FileModel.original_name.like(kw))
        if source_types:
            q = q.filter(FileModel.source_type.in_(source_types))
        if project_id:
            from sqlalchemy import or_
            q = q.filter(or_(
                FileModel.project_id == project_id,
                FileModel.project_id == "",
                FileModel.project_id.is_(None),
            ))
        rows = q.limit(limit).all()
    except Exception as e:
        logger.warning(f"files 搜索失败: {e}")
        return []
    return [
        {**_file_to_dict(r), "match_type": "filename", "score": 0.7}
        for r in rows
    ]


def _file_to_dict(r: FileModel) -> dict:
    tags = []
    if r.tags:
        try:
            tags = json.loads(r.tags)
        except Exception:
            pass
    return {
        "file_id": r.file_id,
        "sha256": r.sha256,
        "file_name": r.original_name,
        "original_path": r.original_path,
        "archive_path": r.archive_path,
        "file_type": r.file_type,
        "source_type": r.source_type,
        "file_size": r.file_size,
        "import_time": str(r.import_time) if r.import_time else None,
        "project_id": r.project_id,
        "category": r.category,
        "tags": tags,
        "parser": r.parser,
        "parse_status": r.parse_status,
        "drawing_id": r.drawing_id,
    }


def _make_snippet(content: str, query: str, radius: int = 80) -> str:
    """Return a snippet around the first match."""
    if not content:
        return ""
    idx = content.lower().find(query.lower())
    if idx == -1:
        return content[: radius * 2].replace("\n", " ")
    start = max(0, idx - radius // 2)
    end = min(len(content), idx + len(query) + radius)
    return content[start:end].replace("\n", " ")
