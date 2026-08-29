"""Unified search result model with source traceability.

Every search result carries provenance (which drawing, which entity,
which layer) so it can be traced back to the original CAD file — a core
requirement of the project.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    """A single unified search result."""

    # What was found
    result_type: str = ""        # "text" | "dimension" | "attribute" | "equipment" | "title_field" | "entity" | "drawing"
    content: str = ""            # human-readable snippet

    # Provenance (来源追溯)
    drawing_id: str = ""
    file_name: str = ""
    entity_id: str = ""
    handle: str = ""
    layer: str = ""
    layout: str = ""

    # Location (for spatial results)
    x: float | None = None
    y: float | None = None

    # Metadata
    extra: dict = Field(default_factory=dict)
    score: float = 1.0           # relevance 0-1

    def summary(self) -> str:
        """Compact one-line description."""
        parts = [f"[{self.result_type}]", self.content]
        if self.layer:
            parts.append(f"图层={self.layer}")
        if self.file_name:
            parts.append(f"文件={self.file_name}")
        if self.handle:
            parts.append(f"handle={self.handle}")
        return " ".join(parts)
