"""Index manager — 索引管理 (Phase 6).

Provides rebuild/clear operations for the vector index, scanning all
drawings in the database and re-embedding their chunks.
"""

from __future__ import annotations

from src.database.connection import get_session
from src.database.repositories import DrawingRepository
from src.index.vector_index import VectorIndex
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.index.manager")


def rebuild_vector_index(clear_first: bool = True) -> int:
    """Rebuild the vector index from all drawings in the database.

    Reads persisted texts/attributes/title fields/equipment/dimensions
    from the database (no re-parsing of source files needed).

    Args:
        clear_first: If True, wipe the whole index before rebuilding.

    Returns:
        Number of chunks indexed.
    """
    from src.chunker.chunker import DocumentChunk

    vi = VectorIndex()

    if clear_first:
        for cid in list(vi._chunks.keys()):
            vi._chunks.pop(cid, None)
            vi._vectors.pop(cid, None)
        if vi._collection is not None:
            try:
                vi._client.delete_collection("cadkb_chunks")
                vi._collection = None
            except Exception as e:
                logger.warning(f"清除旧集合失败: {e}")

    session = get_session()
    repo = DrawingRepository(session)
    drawings = repo.list_drawings(limit=10000)
    session.close()

    total = 0
    for d in drawings:
        try:
            chunks = _chunks_from_db(repo, d.drawing_id, d.file_name)
            if chunks:
                total += vi.index_chunks(chunks)
                logger.info(f"已重建向量: {d.file_name} ({len(chunks)} 块)")
        except Exception as e:
            logger.error(f"重建失败 {d.file_name}: {e}")

    logger.info(f"向量索引重建完成: {total} 块")
    return total


def _chunks_from_db(repo, drawing_id: str, file_name: str) -> list:
    """Build chunks from persisted database rows (no re-parse)."""
    from src.chunker.chunker import DocumentChunk

    chunks: list[DocumentChunk] = []

    # Texts
    for t in repo.get_texts_by_drawing(drawing_id, limit=100000):
        content = (t.get("text_content") or "").strip()
        if not content:
            continue
        chunks.append(DocumentChunk(
            drawing_id=drawing_id,
            source_type="text",
            content=content,
            entity_id=t.get("entity_id", ""),
            handle=t.get("handle", ""),
            layer=t.get("layer", ""),
            metadata={"file_name": file_name, "text_type": t.get("text_type", "")},
        ))

    # Title block fields
    for tb in repo.get_title_blocks_by_drawing(drawing_id):
        for f in tb.get("fields", []):
            key = f.get("key", "")
            value = f.get("value", "")
            if not key and not value:
                continue
            chunks.append(DocumentChunk(
                drawing_id=drawing_id,
                source_type="title_field",
                content=f"{key}: {value}".strip(),
                layer=f.get("layer", ""),
                metadata={"file_name": file_name, "key": key},
            ))

    # Equipment
    for e in repo.get_equipment_by_drawing(drawing_id):
        parts = [e.get("equipment_no", ""), e.get("equipment_name", "")]
        parts = [p for p in parts if p]
        if not parts:
            continue
        chunks.append(DocumentChunk(
            drawing_id=drawing_id,
            source_type="equipment",
            content=" | ".join(parts),
            entity_id=e.get("equipment_id", ""),
            handle=e.get("handle", ""),
            layer=e.get("layer", ""),
            metadata={"file_name": file_name},
        ))

    # Pipes
    for p in repo.get_pipes_by_drawing(drawing_id):
        parts = [p.get("pipe_no", ""), p.get("diameter", ""), p.get("material", "")]
        parts = [x for x in parts if x]
        if not parts:
            continue
        chunks.append(DocumentChunk(
            drawing_id=drawing_id,
            source_type="pipe",
            content=" | ".join(parts),
            handle=p.get("handle", ""),
            layer=p.get("layer", ""),
            metadata={"file_name": file_name},
        ))

    return chunks


def vector_index_stats() -> dict:
    """Return vector index statistics."""
    vi = VectorIndex()
    return {
        "chunks": vi.count(),
        "backend": vi.backend,
        "persist_dir": str(vi.persist_dir),
    }
