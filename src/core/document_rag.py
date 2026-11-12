"""Document vectorization & cross-format RAG (Phase 6).

Word/Excel/PDF/... parsed content -> chunks -> VectorIndex,
so semantic retrieval and QA can hit documents, not only CAD.

Document chunks reuse DocumentChunk with:
  drawing_id = file_id (registry UUID)
  source_type = "document"   (to filter vs CAD chunks)
  metadata = {source_type: real type, title, ...}
"""

from __future__ import annotations

import re

from src.chunker.chunker import DocumentChunk
from src.database.connection import get_session
from src.database.models import DocumentContentModel
from src.index.vector_index import VectorIndex
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.document_rag")

DOC_SOURCE_TYPE = "document"

# 每块最大字符数
CHUNK_SIZE = 500
CHUNK_OVERLAP = 80


def chunk_document_text(
    content: str,
    file_id: str,
    real_source_type: str = "",
    title: str = "",
) -> list[DocumentChunk]:
    """Split document content into overlapping chunks."""
    if not content:
        return []

    # Normalize: split by lines, drop empties
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if not lines:
        return []

    chunks: list[DocumentChunk] = []
    buf = ""
    for ln in lines:
        if len(buf) + len(ln) + 1 > CHUNK_SIZE and buf:
            chunks.append(_make_chunk(buf, file_id, real_source_type, title))
            buf = buf[-CHUNK_OVERLAP:] + "\n"
        buf += ("\n" if buf and not buf.endswith("\n") else "") + ln

    if buf.strip():
        chunks.append(_make_chunk(buf, file_id, real_source_type, title))
    return chunks


def _make_chunk(text: str, file_id: str, real_source_type: str,
                title: str) -> DocumentChunk:
    return DocumentChunk(
        drawing_id=file_id,           # file_id in drawing_id slot
        source_type=DOC_SOURCE_TYPE,  # filterable as "document"
        content=text.strip(),
        metadata={
            "file_id": file_id,
            "source_type": real_source_type or "",
            "title": title or "",
        },
    )


def index_document_content(file_id: str) -> int:
    """Index a document's stored content into the vector DB."""
    session = get_session()
    try:
        rec = (
            session.query(DocumentContentModel)
            .filter(DocumentContentModel.file_id == file_id)
            .first()
        )
        if not rec or not rec.content:
            return 0
        content = rec.content
        real_type = rec.source_type or ""
        title = rec.title or ""
    finally:
        session.close()

    chunks = chunk_document_text(content, file_id, real_type, title)
    if not chunks:
        return 0

    vi = VectorIndex()
    # Remove old document chunks for this file first
    try:
        vi.delete_drawing(file_id)
    except Exception as e:
        logger.warning(f"旧文档向量清理失败 {file_id}: {e}")

    n = vi.index_chunks(chunks)
    logger.info(f"文档向量化: file_id={file_id[:8]} type={real_type} "
                f"chunks={n}")
    return n


def query_documents(query: str, top_k: int = 5, project_id: str = "") -> list[dict]:
    """Vector-search only document chunks.

    Args:
        project_id: 工程隔离（P1）——非空时只返回 平台级 + 本工程 文档块；
            空串 = 平台级查询不过滤。
    """
    vi = VectorIndex()
    return vi.query_project(
        query, top_k=top_k, project_id=project_id,
        where={"source_type": DOC_SOURCE_TYPE},
    )


def delete_document_index(file_id: str) -> int:
    """Remove document chunks of a file."""
    vi = VectorIndex()
    return vi.delete_drawing(file_id)


# ── batch reindex ────────────────────────────────────────────────────

def reindex_all_documents() -> dict:
    """Re-index every document in document_contents (repair utility)."""
    session = get_session()
    try:
        ids = [
            r.file_id for r in session.query(
                DocumentContentModel.file_id).all()
        ]
    finally:
        session.close()

    done = failed = 0
    for fid in ids:
        try:
            n = index_document_content(fid)
            done += 1 if n else 0
        except Exception as e:
            logger.warning(f"文档向量化失败 {fid}: {e}")
            failed += 1
    logger.info(f"文档批量向量化: 成功 {done}, 失败 {failed}")
    return {"done": done, "failed": failed}
