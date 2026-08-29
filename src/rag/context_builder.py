"""Context builder — 上下文构建 (Phase 7).

Builds a structured, traceable context from hybrid retrieval results.
Every context item carries full provenance (来源追溯) per the project
design: file, drawing_id, layout, entity_handle, entity_type, layer,
coordinates, data_tier, confidence.

If provenance is missing, the item is flagged untraceable rather than
guessed.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.utils.logger import setup_logger

logger = setup_logger("cadkb.rag.context")


class SourceInfo(BaseModel):
    """Provenance for a single context item."""
    file: str = ""
    drawing_id: str = ""
    layout: str = ""
    entity_handle: str = ""
    entity_type: str = ""
    layer: str = ""
    coordinates: str = ""


class ContextItem(BaseModel):
    """One context item with its provenance."""
    content: str = ""
    source: SourceInfo = Field(default_factory=SourceInfo)
    data_tier: str = "derived"   # "raw" | "derived" | "ai_inference"
    confidence: float = 1.0
    score: float = 0.0


class BuildContextResult(BaseModel):
    """Result of context building."""
    items: list[ContextItem] = Field(default_factory=list)
    traceable: int = 0          # items with at least drawing_id or file
    untraceable: int = 0        # items with no provenance

    def to_llm_text(self, max_items: int = 10) -> str:
        """Render context items as text for the LLM prompt."""
        lines = []
        for i, item in enumerate(self.items[:max_items], start=1):
            src = item.source
            src_str = ""
            if src.file:
                src_str = f"（来源: {src.file}"
                if src.layer:
                    src_str += f", 图层: {src.layer}"
                if src.entity_handle:
                    src_str += f", handle: {src.entity_handle}"
                src_str += "）"
            elif src.drawing_id:
                src_str = f"（来源: {src.drawing_id[:8]}…）"
            else:
                src_str = "（来源: 无法追溯）"
            lines.append(f"{i}. {item.content} {src_str}")
        return "\n".join(lines)


class ContextBuilder:
    """Build traceable context from hybrid search results."""

    def build(self, results: list[dict], query: str = "") -> BuildContextResult:
        """Convert hybrid search result dicts into ContextItems.

        Args:
            results: List from HybridSearch.search() (each with content,
                source_type, drawing_id, handle, layer, score, metadata).
            query: Original query (unused but kept for future use).

        Returns:
            BuildContextResult with traceable/untraceable counts.
        """
        items: list[ContextItem] = []
        traceable = 0
        untraceable = 0

        for r in results:
            content = (r.get("content") or "").strip()
            if not content:
                continue

            drawing_id = r.get("drawing_id", "") or ""
            handle = r.get("handle", "") or ""
            layer = r.get("layer", "") or ""
            file_name = (r.get("metadata") or {}).get("file_name", "") or ""

            src = SourceInfo(
                file=file_name,
                drawing_id=drawing_id,
                entity_handle=handle,
                layer=layer,
                entity_type=r.get("source_type", ""),
            )

            if drawing_id or file_name or handle:
                traceable += 1
            else:
                untraceable += 1

            items.append(ContextItem(
                content=content,
                source=src,
                data_tier="derived",
                confidence=min(1.0, max(0.0, r.get("score", 0.0))),
                score=r.get("score", 0.0),
            ))

        logger.info(
            f"上下文构建: {len(items)} 项 (可追溯={traceable}, 无法追溯={untraceable})"
        )
        return BuildContextResult(
            items=items, traceable=traceable, untraceable=untraceable
        )


def build_context(results: list[dict], query: str = "") -> BuildContextResult:
    """Convenience wrapper for ContextBuilder().build()."""
    return ContextBuilder().build(results, query)
