"""Backfill document_contents for already-imported documents (Phase 5/6 repair).

Scans `files` for non-CAD records that have ParsedData outputs but are
missing from document_contents, then:
- restores document_contents (content/markdown/paths)
- rebuilds documents_fts row
- re-indexes vectors
- backfills project inference if unassigned

Run:  python -m scripts.backfill_documents
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.database.connection import get_session, init_database  # noqa: E402
from src.database.models import (  # noqa: E402
    DocumentContentModel,
    FileModel,
)
from src.utils.logger import setup_logger  # noqa: E402

logger = setup_logger("cadkb.backfill_docs")

CAD_TYPES = {"dwg", "dxf", "dwt", "dws"}


def backfill_documents() -> dict:
    init_database()
    session = get_session()

    files = (
        session.query(FileModel)
        .filter(~FileModel.source_type.in_(CAD_TYPES))
        .all()
    )

    restored = skipped = errors = 0
    for f in files:
        # Already present?
        rec = (
            session.query(DocumentContentModel)
            .filter(DocumentContentModel.file_id == f.file_id)
            .first()
        )
        if rec:
            skipped += 1
            continue

        # Find ParsedData JSON
        json_path = _find_parsed_json(f.file_id, f.source_type)
        if not json_path:
            skipped += 1
            continue

        try:
            data = json.loads(Path(json_path).read_text(encoding="utf-8"))
            content = data.get("content", "")
            markdown = data.get("markdown", "")
            if not content and not markdown:
                skipped += 1
                continue

            md_path = str(Path(json_path).with_suffix(".md"))
            txt_path = str(Path(json_path).with_suffix(".txt"))
            rec = DocumentContentModel(
                file_id=f.file_id,
                source_type=data.get("source_type", f.source_type),
                title=data.get("title", f.original_name),
                content=content,
                markdown=markdown,
                json_path=str(json_path),
                md_path=md_path,
                txt_path=txt_path,
                source=data.get("source", "text"),
                confidence=data.get("confidence", 1.0),
            )
            session.add(rec)
            session.commit()
            restored += 1

            # Rebuild FTS + vectors + project (non-fatal)
            try:
                _rebuild_fts(rec)
                from src.core.document_rag import index_document_content

                index_document_content(f.file_id)
            except Exception as e:
                logger.warning(f"索引重建失败 {f.file_id}: {e}")
            try:
                from src.core.project_inference import assign_project_to_file

                if not f.project_id:
                    assign_project_to_file(
                        f.file_id, f.original_name, f.original_path,
                        doc_title=data.get("title", ""))
            except Exception as e:
                logger.warning(f"项目推断失败 {f.file_id}: {e}")
        except Exception as e:
            logger.warning(f"回填失败 {f.file_id}: {e}")
            errors += 1

    session.close()
    logger.info(f"回填完成: 恢复 {restored}, 跳过 {skipped}, 错误 {errors}")
    return {"restored": restored, "skipped": skipped, "errors": errors}


def _find_parsed_json(file_id: str, source_type: str) -> Path | None:
    """Locate ParsedData JSON for a file (by source_type dir)."""
    from src.core.config import get_config

    cfg = get_config()
    candidates = [
        cfg.parsed_dir / source_type / f"{file_id}.json",
    ]
    # try other doc dirs as fallback
    for sub in ("word", "excel", "pdf", "other"):
        p = cfg.parsed_dir / sub / f"{file_id}.json"
        if p.exists():
            return p
    for c in candidates:
        if c.exists():
            return c
    return None


def _rebuild_fts(rec) -> None:
    from sqlalchemy import text

    from src.database.connection import get_session

    session = get_session()
    try:
        session.execute(text(
            "DELETE FROM documents_fts WHERE file_id = :fid"
        ), {"fid": rec.file_id})
        session.execute(text(
            """
            INSERT INTO documents_fts (title, content, file_id, source_type)
            VALUES (:title, :content, :fid, :st)
            """
        ), {
            "title": rec.title or "",
            "content": rec.content or "",
            "fid": rec.file_id,
            "st": rec.source_type or "",
        })
        session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    backfill_documents()
