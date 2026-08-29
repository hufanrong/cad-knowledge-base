"""Drawing comparison — 图纸差异比较 (Phase 9).

Compares two drawings and produces a structured difference report:

- Entity-level diff: geometry signature matching, flags ADDED / REMOVED / MODIFIED
- Text diff: content changes
- Dimension diff: measurement/text changes
- Semantic diff: equipment & title-block field changes

Everything is deterministic and traceable (each diff entry carries the
source handle/layer where available).
"""

from __future__ import annotations

import hashlib
from pydantic import BaseModel, Field

from src.normalizer.schema import ParseResult
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.compare")


class EntityChange(BaseModel):
    """A single entity-level change."""
    status: str = ""            # "added" | "removed" | "modified"
    entity_type: str = ""
    layer: str = ""
    handle: str = ""
    detail: str = ""


class TextChange(BaseModel):
    """A single text change."""
    status: str = ""            # "added" | "removed" | "modified"
    old_content: str = ""
    new_content: str = ""
    layer: str = ""
    handle: str = ""
    detail: str = ""            # optional extra (e.g. title-block field key)


class DimensionChange(BaseModel):
    """A single dimension change."""
    status: str = ""            # "added" | "removed" | "modified"
    old_text: str = ""
    new_text: str = ""
    old_measurement: float | None = None
    new_measurement: float | None = None
    layer: str = ""
    handle: str = ""


class CompareReport(BaseModel):
    """Full comparison report between two drawings."""
    drawing_a: str = ""         # file names
    drawing_b: str = ""
    entity_added: list[EntityChange] = Field(default_factory=list)
    entity_removed: list[EntityChange] = Field(default_factory=list)
    entity_modified: list[EntityChange] = Field(default_factory=list)
    texts_added: list[TextChange] = Field(default_factory=list)
    texts_removed: list[TextChange] = Field(default_factory=list)
    texts_modified: list[TextChange] = Field(default_factory=list)
    dimensions_added: list[DimensionChange] = Field(default_factory=list)
    dimensions_removed: list[DimensionChange] = Field(default_factory=list)
    dimensions_modified: list[DimensionChange] = Field(default_factory=list)
    equipment_added: list[str] = Field(default_factory=list)
    equipment_removed: list[str] = Field(default_factory=list)
    title_field_changes: list[TextChange] = Field(default_factory=list)

    @property
    def summary(self) -> dict:
        """Compact statistics."""
        return {
            "entities": {
                "added": len(self.entity_added),
                "removed": len(self.entity_removed),
                "modified": len(self.entity_modified),
            },
            "texts": {
                "added": len(self.texts_added),
                "removed": len(self.texts_removed),
                "modified": len(self.texts_modified),
            },
            "dimensions": {
                "added": len(self.dimensions_added),
                "removed": len(self.dimensions_removed),
                "modified": len(self.dimensions_modified),
            },
            "equipment": {
                "added": len(self.equipment_added),
                "removed": len(self.equipment_removed),
            },
            "title_fields": len(self.title_field_changes),
        }

    @property
    def total_changes(self) -> int:
        s = self.summary
        return (
            sum(s["entities"].values())
            + sum(s["texts"].values())
            + sum(s["dimensions"].values())
            + sum(s["equipment"].values())
            + s["title_fields"]
        )


def _entity_signature(e) -> str:
    """Deterministic fingerprint of an entity's geometry."""
    coords = [round(c, 3) for c in (e.coordinates or [])]
    payload = f"{e.entity_type}|{e.layer}|{coords}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class DrawingComparer:
    """Compare two parsed drawings."""

    def compare(
        self,
        result_a: ParseResult,
        result_b: ParseResult,
        file_name_a: str = "",
        file_name_b: str = "",
    ) -> CompareReport:
        """Compare two ParseResults and build a report."""
        report = CompareReport(
            drawing_a=file_name_a or result_a.drawing.file_name,
            drawing_b=file_name_b or result_b.drawing.file_name,
        )

        # 1. Entity-level comparison via geometry signatures
        self._compare_entities(result_a, result_b, report)

        # 2. Text comparison
        self._compare_texts(result_a, result_b, report)

        # 3. Dimension comparison
        self._compare_dimensions(result_a, result_b, report)

        # 4. Semantic comparison (equipment / title block fields)
        self._compare_semantic(result_a, result_b, report)

        logger.info(
            f"比较完成: {report.drawing_a} vs {report.drawing_b} "
            f"(变更 {report.total_changes} 项)"
        )
        return report

    # ── entity level ─────────────────────────────────────────────────

    def _compare_entities(self, a: ParseResult, b: ParseResult, report: CompareReport):
        sig_a = {_entity_signature(e): e for e in a.entities if e.entity_id}
        sig_b = {_entity_signature(e): e for e in b.entities if e.entity_id}

        for sig, e in sig_a.items():
            if sig not in sig_b:
                report.entity_removed.append(EntityChange(
                    status="removed",
                    entity_type=e.entity_type,
                    layer=e.layer,
                    handle=e.handle or "",
                    detail=self._entity_detail(e),
                ))

        for sig, e in sig_b.items():
            if sig not in sig_a:
                report.entity_added.append(EntityChange(
                    status="added",
                    entity_type=e.entity_type,
                    layer=e.layer,
                    handle=e.handle or "",
                    detail=self._entity_detail(e),
                ))

        # Modified: same handle, different signature
        # (map handle->signature within each drawing)
        handle_a: dict[str, str] = {
            e.handle: _entity_signature(e) for e in a.entities if e.handle
        }
        handle_b: dict[str, str] = {
            e.handle: _entity_signature(e) for e in b.entities if e.handle
        }
        for handle in set(handle_a) & set(handle_b):
            if handle_a[handle] != handle_b[handle]:
                ea = next(e for e in a.entities if e.handle == handle)
                eb = next(e for e in b.entities if e.handle == handle)
                report.entity_modified.append(EntityChange(
                    status="modified",
                    entity_type=eb.entity_type,
                    layer=eb.layer,
                    handle=handle,
                    detail=f"{self._entity_detail(ea)} → {self._entity_detail(eb)}",
                ))

    @staticmethod
    def _entity_detail(e) -> str:
        coords = e.coordinates or []
        if len(coords) >= 2:
            return f"({coords[0]:.1f},{coords[1]:.1f}) {e.entity_type}"
        return e.entity_type

    # ── texts ────────────────────────────────────────────────────────

    def _compare_texts(self, a: ParseResult, b: ParseResult, report: CompareReport):
        # Map by (layer, position rounded) — handle may change between versions
        def key(t):
            pos = t.position or (0, 0, 0)
            return (t.layer or "", round(pos[0], 2), round(pos[1], 2))

        map_a = {key(t): t for t in a.texts}
        map_b = {key(t): t for t in b.texts}

        for k, t in map_a.items():
            if k not in map_b:
                report.texts_removed.append(TextChange(
                    status="removed",
                    old_content=t.text_content,
                    layer=t.layer,
                    handle=t.handle or "",
                ))
            elif map_b[k].text_content != t.text_content:
                report.texts_modified.append(TextChange(
                    status="modified",
                    old_content=t.text_content,
                    new_content=map_b[k].text_content,
                    layer=t.layer,
                    handle=t.handle or "",
                ))

        for k, t in map_b.items():
            if k not in map_a:
                report.texts_added.append(TextChange(
                    status="added",
                    new_content=t.text_content,
                    layer=t.layer,
                    handle=t.handle or "",
                ))

    # ── dimensions ───────────────────────────────────────────────────

    def _compare_dimensions(self, a: ParseResult, b: ParseResult, report: CompareReport):
        def key(d):
            return (d.layer or "", d.measurement, d.text_content or "")

        map_a = {key(d): d for d in a.dimensions}
        map_b = {key(d): d for d in b.dimensions}

        for k, d in map_a.items():
            if k not in map_b:
                report.dimensions_removed.append(DimensionChange(
                    status="removed",
                    old_text=d.text_content or "",
                    old_measurement=d.measurement,
                    layer=d.layer,
                    handle=d.handle or "",
                ))

        for k, d in map_b.items():
            if k not in map_a:
                report.dimensions_added.append(DimensionChange(
                    status="added",
                    new_text=d.text_content or "",
                    new_measurement=d.measurement,
                    layer=d.layer,
                    handle=d.handle or "",
                ))

        # Modified: same location-ish by layer + old measurement? Use text hash
        # Simpler: match by dimension_type+layer when measurement differs
        pos_a = {(d.layer or "", d.handle): d for d in a.dimensions if d.handle}
        pos_b = {(d.layer or "", d.handle): d for d in b.dimensions if d.handle}
        for k in set(pos_a) & set(pos_b):
            da, db = pos_a[k], pos_b[k]
            if (da.measurement != db.measurement
                    or (da.text_content or "") != (db.text_content or "")):
                report.dimensions_modified.append(DimensionChange(
                    status="modified",
                    old_text=da.text_content or "",
                    new_text=db.text_content or "",
                    old_measurement=da.measurement,
                    new_measurement=db.measurement,
                    layer=db.layer,
                    handle=db.handle or "",
                ))

    # ── semantic ─────────────────────────────────────────────────────

    def _compare_semantic(self, a: ParseResult, b: ParseResult, report: CompareReport):
        # Equipment by (no, name)
        eq_a = {(e.equipment_no or "", e.equipment_name or "") for e in a.equipment}
        eq_b = {(e.equipment_no or "", e.equipment_name or "") for e in b.equipment}
        for item in eq_a - eq_b:
            report.equipment_removed.append(" | ".join(x for x in item if x))
        for item in eq_b - eq_a:
            report.equipment_added.append(" | ".join(x for x in item if x))

        # Title block fields by key
        fields_a: dict[str, str] = {}
        for tb in a.title_blocks:
            for f in tb.fields:
                fields_a[f.key] = f.value
        fields_b: dict[str, str] = {}
        for tb in b.title_blocks:
            for f in tb.fields:
                fields_b[f.key] = f.value

        for k in sorted(set(fields_a) & set(fields_b)):
            if fields_a[k] != fields_b[k]:
                report.title_field_changes.append(TextChange(
                    status="modified",
                    old_content=fields_a[k],
                    new_content=fields_b[k],
                    layer="标题栏",
                    detail=k,
                ))


def compare_drawings(
    result_a: ParseResult,
    result_b: ParseResult,
    file_name_a: str = "",
    file_name_b: str = "",
) -> CompareReport:
    """Convenience wrapper for DrawingComparer().compare()."""
    return DrawingComparer().compare(result_a, result_b, file_name_a, file_name_b)
