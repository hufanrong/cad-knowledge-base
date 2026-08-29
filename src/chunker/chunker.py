"""Document chunker — 文档分块 (Phase 6).

Converts parsed drawing content into searchable chunks. Each chunk
carries full provenance (drawing_id, entity_id, layer, handle) so RAG
results can be traced back to the original CAD file.

Chunk sources:
- Text entities (TEXT / MTEXT)
- Block attributes (tag: value)
- Title block fields (key: value)
- Dimension texts
- Equipment entries
- Pipe entries
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.normalizer.schema import ParseResult
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.chunker")


class DocumentChunk(BaseModel):
    """A single chunk of drawing content for indexing."""
    chunk_id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex)
    drawing_id: str = ""
    source_type: str = ""    # "text" | "attribute" | "title_field" | "dimension" | "equipment" | "pipe"
    content: str = ""        # clean text
    entity_id: str = ""
    handle: str = ""
    layer: str = ""
    layout: str = ""
    x: float | None = None
    y: float | None = None
    metadata: dict = Field(default_factory=dict)


class Chunker:
    """Build chunks from a ParseResult."""

    def chunk(self, result: ParseResult) -> list[DocumentChunk]:
        """Convert a ParseResult into a list of chunks.

        Returns:
            List of DocumentChunk. Empty content chunks are skipped.
        """
        chunks: list[DocumentChunk] = []
        drawing_id = result.drawing.drawing_id

        # 1. Text entities
        for t in result.texts:
            content = (t.text_content or "").strip()
            if not content:
                continue
            chunks.append(DocumentChunk(
                drawing_id=drawing_id,
                source_type="text",
                content=content,
                entity_id=t.entity_id,
                handle=t.handle or "",
                layer=t.layer or "",
                layout=t.layout or "",
                x=t.position[0] if t.position else None,
                y=t.position[1] if t.position else None,
                metadata={"text_type": t.text_type},
            ))

        # 2. Block attributes
        for a in result.attributes:
            content = f"{a.tag or ''}: {a.value or ''}".strip()
            if not content or content == ":":
                continue
            chunks.append(DocumentChunk(
                drawing_id=drawing_id,
                source_type="attribute",
                content=content,
                entity_id=a.attrib_id,
                handle=a.handle or "",
                layer=a.layer or "",
                metadata={"block_name": a.block_name or "", "tag": a.tag or ""},
            ))

        # 3. Title block fields
        for tb in result.title_blocks:
            for f in tb.fields:
                if not f.key and not f.value:
                    continue
                chunks.append(DocumentChunk(
                    drawing_id=drawing_id,
                    source_type="title_field",
                    content=f"{f.key}: {f.value}".strip(),
                    handle=f.handle or "",
                    layer=f.layer or "",
                    x=f.x,
                    y=f.y,
                    metadata={"key": f.key},
                ))

        # 4. Dimensions
        for d in result.dimensions:
            content = (d.text_content or "").strip()
            if not content and d.measurement is not None:
                content = f"{d.dimension_type} {d.measurement}"
            if not content:
                continue
            chunks.append(DocumentChunk(
                drawing_id=drawing_id,
                source_type="dimension",
                content=content,
                entity_id=d.entity_id,
                handle=d.handle or "",
                layer=d.layer or "",
                metadata={"dimension_type": d.dimension_type, "measurement": d.measurement},
            ))

        # 5. Equipment
        for e in result.equipment:
            parts = []
            if e.equipment_no:
                parts.append(e.equipment_no)
            if e.equipment_name:
                parts.append(e.equipment_name)
            if not parts:
                continue
            chunks.append(DocumentChunk(
                drawing_id=drawing_id,
                source_type="equipment",
                content=" | ".join(parts),
                entity_id=e.equipment_id,
                handle=e.handle or "",
                layer=e.layer or "",
                x=e.x,
                y=e.y,
                metadata={"equipment_no": e.equipment_no, "confidence": e.confidence},
            ))

        # 6. Pipes
        for p in result.pipes:
            parts = []
            if p.pipe_no:
                parts.append(p.pipe_no)
            if p.diameter:
                parts.append(p.diameter)
            if p.material:
                parts.append(p.material)
            if not parts:
                continue
            chunks.append(DocumentChunk(
                drawing_id=drawing_id,
                source_type="pipe",
                content=" | ".join(parts),
                entity_id=p.pipe_id,
                handle=p.handle or "",
                layer=p.layer or "",
                x=p.x,
                y=p.y,
                metadata={"confidence": p.confidence},
            ))

        logger.info(f"分块: 生成 {len(chunks)} 个块")
        return chunks


def chunk_result(result: ParseResult) -> list[DocumentChunk]:
    """Convenience wrapper for Chunker().chunk()."""
    return Chunker().chunk(result)
