"""Unified search service — 统一搜索入口 (Phase 5).

Provides three search modes:
1. Full-text search (SQLite FTS5)
2. Structured search (SQL on layers / types / equipment / title blocks)
3. Spatial search (bbox region / near entity / spatial relationships)

All results are SearchResult objects carrying full provenance.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from src.database.connection import get_session
from src.database.models import (
    DrawingModel,
    EntityModel,
    EquipmentModel,
    PipeModel,
    SpatialRelationshipModel,
    TextModel,
    TitleBlockFieldModel,
)
from src.index.search_result import SearchResult
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.search")

# Entity types worth returning in generic searches (exclude noise)
SIGNIFICANT_TYPES = {
    "LINE", "CIRCLE", "ARC", "LWPOLYLINE", "POLYLINE", "SPLINE", "ELLIPSE",
    "TEXT", "MTEXT", "DIMENSION", "INSERT", "HATCH", "POINT", "LEADER",
}


class SearchService:
    """Unified search entry point."""

    def __init__(self, session=None):
        self.session = session or get_session()

    def close(self):
        self.session.close()

    # ── Unified entry ───────────────────────────────────────────────

    def search(
        self,
        query: str = "",
        search_type: str = "all",
        layer: str | None = None,
        drawing_id: str | None = None,
        entity_type: str | None = None,
        limit: int = 50,
        project_id: str = "",
    ) -> list[SearchResult]:
        """Unified search across all indexes.

        Args:
            query: Keyword string (for full-text / structured match).
            search_type: "all" | "text" | "attribute" | "equipment" |
                "title_field" | "entity" | "drawing" | "dimension".
            layer: Filter by layer name (exact).
            drawing_id: Filter by drawing.
            entity_type: Filter by entity type (e.g. "LINE").
            limit: Max results.
            project_id: 工程隔离（P1）——非空时只返回 平台级(空/None) + 本工程 资料；
                空串 = 平台级查询，不过滤。

        Returns:
            List of SearchResult (with provenance).
        """
        results: list[SearchResult] = []

        if search_type in ("all", "text", "attribute", "entity", "drawing"):
            results += self.search_fulltext(
                query, search_type=search_type, layer=layer,
                drawing_id=drawing_id, limit=limit, project_id=project_id,
            )

        if search_type in ("all", "equipment"):
            results += self.search_equipment(
                query, layer=layer, drawing_id=drawing_id, limit=limit,
                project_id=project_id,
            )

        if search_type in ("all", "title_field"):
            results += self.search_title_fields(
                query, layer=layer, drawing_id=drawing_id, limit=limit,
                project_id=project_id,
            )

        if search_type in ("all", "dimension"):
            results += self.search_dimensions(
                query, layer=layer, drawing_id=drawing_id, limit=limit,
                project_id=project_id,
            )

        if search_type == "entity" and entity_type:
            results += self.search_by_entity_type(
                entity_type, layer=layer, drawing_id=drawing_id, limit=limit,
                project_id=project_id,
            )

        # Sort by score desc, then dedupe by (result_type, drawing_id, entity_id, content)
        results.sort(key=lambda r: r.score, reverse=True)
        seen: set[tuple] = set()
        deduped: list[SearchResult] = []
        for r in results:
            key = (r.result_type, r.drawing_id, r.entity_id, r.content)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(r)
            if len(deduped) >= limit:
                break

        return deduped

    # ── project isolation helpers (P1) ─────────────────────────────

    @staticmethod
    def _project_clause_sql(alias: str, params: dict, project_id: str) -> str:
        """SQL 工程过滤片段：保留 平台级(空/None) + 本工程；project_id 空不过滤。"""
        if not project_id:
            return ""
        params["pid"] = project_id
        return (
            f" AND ({alias}.project_id = :pid OR {alias}.project_id = '' "
            f"OR {alias}.project_id IS NULL)"
        )

    @staticmethod
    def _apply_project_orm(q, model, project_id: str):
        """ORM query 工程过滤（join drawings -> files）；project_id 空不过滤。"""
        if not project_id:
            return q
        from sqlalchemy import or_
        from src.database.models import DrawingModel, FileModel
        return (
            q.join(DrawingModel, DrawingModel.drawing_id == model.drawing_id)
            .join(FileModel, FileModel.drawing_id == DrawingModel.drawing_id)
            .filter(or_(
                FileModel.project_id == "",
                FileModel.project_id == project_id,
                FileModel.project_id.is_(None),
            ))
        )

    # ── Full-text search ────────────────────────────────────────────

    def search_fulltext(
        self,
        query: str,
        search_type: str = "text",
        layer: str | None = None,
        drawing_id: str | None = None,
        limit: int = 50,
        project_id: str = "",
    ) -> list[SearchResult]:
        """Full-text search via FTS5.

        If query is empty, falls back to structured text listing when a
        layer or drawing_id filter is present.
        """
        if not query and not layer and not drawing_id:
            return []

        results: list[SearchResult] = []
        q = query.replace('"', '')

        if search_type in ("all", "text"):
            if q:
                results += self._fts_texts(q, layer, drawing_id, limit, project_id)
            elif layer or drawing_id:
                # Structured query: list texts by layer/drawing
                results += self._structured_texts(layer, drawing_id, limit, project_id)

        if search_type in ("all", "attribute"):
            if q:
                results += self._fts_attributes(q, drawing_id, limit, project_id)

        if search_type in ("all", "drawing"):
            if q:
                results += self._fts_drawings(q, limit, project_id)

        return results

    def _structured_texts(
        self,
        layer: str | None,
        drawing_id: str | None,
        limit: int,
        project_id: str = "",
    ) -> list[SearchResult]:
        """Structured query: return texts by layer/drawing (no keyword)."""
        q = self.session.query(TextModel)
        if layer:
            q = q.filter(TextModel.layer == layer)
        if drawing_id:
            q = q.filter(TextModel.drawing_id == drawing_id)
        q = self._apply_project_orm(q, TextModel, project_id)
        rows = q.limit(limit).all()

        # Resolve file names
        dids = {r.drawing_id for r in rows}
        file_names: dict[str, str] = {}
        if dids:
            draws = (
                self.session.query(DrawingModel.drawing_id, DrawingModel.file_name)
                .filter(DrawingModel.drawing_id.in_(dids))
                .all()
            )
            file_names = {did: fname for did, fname in draws}

        return [
            SearchResult(
                result_type="text",
                content=t.text_content or "",
                drawing_id=t.drawing_id,
                entity_id=t.entity_id,
                layer=t.layer or "",
                layout=t.layout or "",
                handle=t.handle or "",
                file_name=file_names.get(t.drawing_id, ""),
                score=0.5,
            )
            for t in rows
        ]

    def _fts_texts(self, q: str, layer: str | None, drawing_id: str | None,
                   limit: int, project_id: str = "") -> list[SearchResult]:
        try:
            sql = (
                "SELECT f.text_content, f.drawing_id, f.entity_id, f.layer, f.layout, "
                "       COALESCE(t.handle, ''), d.file_name "
                "FROM texts_fts f "
                "JOIN texts t ON t.entity_id = f.entity_id "
                "JOIN drawings d ON d.drawing_id = f.drawing_id "
                "LEFT JOIN files fl ON fl.drawing_id = d.drawing_id "
                "WHERE texts_fts MATCH :q "
            )
            params: dict[str, Any] = {"q": q}
            if layer:
                sql += " AND f.layer = :layer"
                params["layer"] = layer
            if drawing_id:
                sql += " AND f.drawing_id = :did"
                params["did"] = drawing_id
            sql += self._project_clause_sql("fl", params, project_id)
            sql += " LIMIT :limit"
            params["limit"] = limit

            rows = self.session.execute(text(sql), params).fetchall()
            return [
                SearchResult(
                    result_type="text",
                    content=r[0],
                    drawing_id=r[1],
                    entity_id=r[2],
                    layer=r[3] or "",
                    layout=r[4] or "",
                    handle=r[5] or "",
                    file_name=r[6] or "",
                    score=0.8,
                )
                for r in rows
            ]
        except Exception as e:
            logger.warning(f"FTS text 搜索失败: {e}")
            return []

    def _fts_attributes(self, q: str, drawing_id: str | None,
                        limit: int, project_id: str = "") -> list[SearchResult]:
        try:
            sql = (
                "SELECT a.value, a.drawing_id, a.block_name, a.tag, d.file_name "
                "FROM attributes_fts a "
                "JOIN drawings d ON d.drawing_id = a.drawing_id "
                "LEFT JOIN files fl ON fl.drawing_id = d.drawing_id "
                "WHERE attributes_fts MATCH :q "
            )
            params: dict[str, Any] = {"q": q}
            if drawing_id:
                sql += " AND a.drawing_id = :did"
                params["did"] = drawing_id
            sql += self._project_clause_sql("fl", params, project_id)
            sql += " LIMIT :limit"
            params["limit"] = limit

            rows = self.session.execute(text(sql), params).fetchall()
            return [
                SearchResult(
                    result_type="attribute",
                    content=f"{r[3]}: {r[0]}",
                    drawing_id=r[1],
                    layer=r[2] or "",
                    extra={"tag": r[3], "block_name": r[2]},
                    file_name=r[4] or "",
                    score=0.7,
                )
                for r in rows
            ]
        except Exception as e:
            logger.warning(f"FTS attribute 搜索失败: {e}")
            return []

    def _fts_drawings(self, q: str, limit: int, project_id: str = "") -> list[SearchResult]:
        try:
            sql = (
                "SELECT d.file_name, d.drawing_id FROM drawings_fts f "
                "JOIN drawings d ON d.drawing_id = f.drawing_id "
                "LEFT JOIN files fl ON fl.drawing_id = d.drawing_id "
                "WHERE drawings_fts MATCH :q "
            )
            params: dict[str, Any] = {"q": q}
            sql += self._project_clause_sql("fl", params, project_id)
            sql += " LIMIT :limit"
            params["limit"] = limit
            rows = self.session.execute(text(sql), params).fetchall()
            return [
                SearchResult(
                    result_type="drawing",
                    content=r[0],
                    drawing_id=r[1],
                    file_name=r[0],
                    score=0.9,
                )
                for r in rows
            ]
        except Exception as e:
            logger.warning(f"FTS drawing 搜索失败: {e}")
            return []

    # ── Structured search ───────────────────────────────────────────

    def search_equipment(
        self,
        query: str = "",
        layer: str | None = None,
        drawing_id: str | None = None,
        limit: int = 50,
        project_id: str = "",
    ) -> list[SearchResult]:
        """Search equipment by number/name."""
        q = self.session.query(EquipmentModel)
        if query:
            like = f"%{query}%"
            from sqlalchemy import or_
            q = q.filter(or_(
                EquipmentModel.equipment_no.like(like),
                EquipmentModel.equipment_name.like(like),
            ))
        if layer:
            q = q.filter(EquipmentModel.layer == layer)
        if drawing_id:
            q = q.filter(EquipmentModel.drawing_id == drawing_id)
        q = self._apply_project_orm(q, EquipmentModel, project_id)
        rows = q.limit(limit).all()

        results = []
        for e in rows:
            content = f"{e.equipment_no or '?'} | {e.equipment_name or '?'}"
            if e.equipment_name and query and query.lower() in (e.equipment_name or "").lower():
                score = 0.95
            elif e.equipment_no and query and query.lower() in (e.equipment_no or "").lower():
                score = 0.95
            else:
                score = 0.6
            results.append(SearchResult(
                result_type="equipment",
                content=content,
                drawing_id=e.drawing_id,
                entity_id=e.equipment_id,
                handle=e.handle or "",
                layer=e.layer or "",
                x=e.x,
                y=e.y,
                extra={
                    "equipment_no": e.equipment_no,
                    "equipment_name": e.equipment_name,
                    "confidence": e.confidence,
                },
                score=score,
            ))
        return results

    def search_title_fields(
        self,
        query: str = "",
        layer: str | None = None,
        drawing_id: str | None = None,
        limit: int = 50,
        project_id: str = "",
    ) -> list[SearchResult]:
        """Search title block fields by key or value."""
        q = self.session.query(TitleBlockFieldModel)
        if query:
            like = f"%{query}%"
            from sqlalchemy import or_
            q = q.filter(or_(
                TitleBlockFieldModel.key.like(like),
                TitleBlockFieldModel.value.like(like),
            ))
        if layer:
            q = q.filter(TitleBlockFieldModel.layer == layer)
        if drawing_id:
            q = q.filter(TitleBlockFieldModel.drawing_id == drawing_id)
        q = self._apply_project_orm(q, TitleBlockFieldModel, project_id)
        rows = q.limit(limit).all()

        results = []
        for f in rows:
            results.append(SearchResult(
                result_type="title_field",
                content=f"{f.key}: {f.value}",
                drawing_id=f.drawing_id,
                handle=f.handle or "",
                layer=f.layer or "",
                x=f.x,
                y=f.y,
                extra={"key": f.key, "value": f.value},
                score=0.75,
            ))
        return results

    def search_dimensions(
        self,
        query: str = "",
        layer: str | None = None,
        drawing_id: str | None = None,
        limit: int = 50,
        project_id: str = "",
    ) -> list[SearchResult]:
        """Search dimensions by text content or measurement."""
        from src.database.models import DimensionModel

        q = self.session.query(DimensionModel)
        if query:
            like = f"%{query}%"
            q = q.filter(DimensionModel.text_content.like(like))
        if layer:
            q = q.filter(DimensionModel.layer == layer)
        if drawing_id:
            q = q.filter(DimensionModel.drawing_id == drawing_id)
        q = self._apply_project_orm(q, DimensionModel, project_id)
        rows = q.limit(limit).all()

        results = []
        for d in rows:
            content = f"{d.dimension_type}: {d.measurement} ({d.text_content or ''})"
            results.append(SearchResult(
                result_type="dimension",
                content=content,
                drawing_id=d.drawing_id,
                entity_id=d.entity_id,
                handle=d.handle or "",
                layer=d.layer or "",
                extra={"dimension_type": d.dimension_type, "measurement": d.measurement},
                score=0.65,
            ))
        return results

    def search_by_entity_type(
        self,
        entity_type: str,
        layer: str | None = None,
        drawing_id: str | None = None,
        limit: int = 50,
        project_id: str = "",
    ) -> list[SearchResult]:
        """Search entities by type (structured query)."""
        q = self.session.query(EntityModel).filter(
            EntityModel.entity_type == entity_type
        )
        if layer:
            q = q.filter(EntityModel.layer == layer)
        if drawing_id:
            q = q.filter(EntityModel.drawing_id == drawing_id)
        q = self._apply_project_orm(q, EntityModel, project_id)
        rows = q.limit(limit).all()

        results = []
        for e in rows:
            results.append(SearchResult(
                result_type="entity",
                content=f"{e.entity_type} @ layer={e.layer}",
                drawing_id=e.drawing_id,
                entity_id=e.entity_id,
                handle=e.handle or "",
                layer=e.layer or "",
                layout=e.layout or "",
                extra={
                    "entity_type": e.entity_type,
                    "bbox": [
                        e.bbox_min_x, e.bbox_min_y, e.bbox_max_x, e.bbox_max_y,
                    ],
                },
                score=0.5,
            ))
        return results

    # ── Spatial search ──────────────────────────────────────────────

    def search_in_region(
        self,
        min_x: float,
        min_y: float,
        max_x: float,
        max_y: float,
        drawing_id: str | None = None,
        entity_types: list[str] | None = None,
        limit: int = 100,
    ) -> list[SearchResult]:
        """Find entities whose bbox is inside the given region."""
        q = self.session.query(EntityModel).filter(
            EntityModel.bbox_min_x >= min_x,
            EntityModel.bbox_min_y >= min_y,
            EntityModel.bbox_max_x <= max_x,
            EntityModel.bbox_max_y <= max_y,
        )
        if drawing_id:
            q = q.filter(EntityModel.drawing_id == drawing_id)
        if entity_types:
            q = q.filter(EntityModel.entity_type.in_(entity_types))
        rows = q.limit(limit).all()

        # Resolve file names for provenance
        file_names: dict[str, str] = {}
        dids = {r.drawing_id for r in rows}
        if dids:
            draws = (
                self.session.query(DrawingModel.drawing_id, DrawingModel.file_name)
                .filter(DrawingModel.drawing_id.in_(dids))
                .all()
            )
            file_names = {did: fname for did, fname in draws}

        results = []
        for e in rows:
            results.append(SearchResult(
                result_type="entity",
                content=f"{e.entity_type} @ ({e.bbox_min_x:.1f},{e.bbox_min_y:.1f})",
                drawing_id=e.drawing_id,
                entity_id=e.entity_id,
                handle=e.handle or "",
                layer=e.layer or "",
                layout=e.layout or "",
                x=(e.bbox_min_x + e.bbox_max_x) / 2,
                y=(e.bbox_min_y + e.bbox_max_y) / 2,
                file_name=file_names.get(e.drawing_id, ""),
                extra={"entity_type": e.entity_type, "in_region": True},
                score=0.9,
            ))
        return results

    def search_near_entity(
        self,
        entity_id: str,
        rel_type: str | None = None,
        limit: int = 100,
    ) -> list[SearchResult]:
        """Find entities near a given entity via spatial relationships."""
        q = self.session.query(SpatialRelationshipModel).filter(
            (SpatialRelationshipModel.entity_a_id == entity_id)
            | (SpatialRelationshipModel.entity_b_id == entity_id)
        )
        if rel_type:
            q = q.filter(SpatialRelationshipModel.relationship_type == rel_type)
        rows = q.limit(limit).all()

        # Resolve the "other" entity for each relationship
        results = []
        other_ids: dict[str, dict] = {}
        for r in rows:
            other = r.entity_b_id if r.entity_a_id == entity_id else r.entity_a_id
            other_ids[other] = {
                "rel_type": r.relationship_type,
                "distance": r.distance,
                "confidence": r.confidence,
            }

        if other_ids:
            ents = (
                self.session.query(EntityModel)
                .filter(EntityModel.entity_id.in_(other_ids.keys()))
                .all()
            )
            for e in ents:
                rel = other_ids[e.entity_id]
                results.append(SearchResult(
                    result_type="entity",
                    content=f"{e.entity_type} @ layer={e.layer}",
                    drawing_id=e.drawing_id,
                    entity_id=e.entity_id,
                    handle=e.handle or "",
                    layer=e.layer or "",
                    extra={
                        "entity_type": e.entity_type,
                        "rel_type": rel["rel_type"].value
                        if hasattr(rel["rel_type"], "value") else str(rel["rel_type"]),
                        "distance": rel["distance"],
                        "confidence": rel["confidence"],
                    },
                    score=rel.get("confidence", 0.5) * 0.9,
                ))

        return results


def search(
    query: str = "",
    search_type: str = "all",
    layer: str | None = None,
    drawing_id: str | None = None,
    entity_type: str | None = None,
    limit: int = 50,
) -> list[SearchResult]:
    """Convenience function: run a unified search."""
    svc = SearchService()
    try:
        return svc.search(
            query=query,
            search_type=search_type,
            layer=layer,
            drawing_id=drawing_id,
            entity_type=entity_type,
            limit=limit,
        )
    finally:
        svc.close()


def search_in_region(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    drawing_id: str | None = None,
    entity_types: list[str] | None = None,
    limit: int = 100,
) -> list[SearchResult]:
    """Convenience function: spatial region search."""
    svc = SearchService()
    try:
        return svc.search_in_region(
            min_x, min_y, max_x, max_y,
            drawing_id=drawing_id, entity_types=entity_types, limit=limit,
        )
    finally:
        svc.close()
