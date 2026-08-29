"""Data access layer — converts Pydantic schema to ORM and persists."""

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.database.connection import get_session
from src.database.models import (
    BlockAttributeModel,
    BlockDefModel,
    DimensionModel,
    DrawingFrameModel,
    DrawingModel,
    EntityModel,
    EquipmentModel,
    LayerModel,
    LayoutModel,
    ParseLogModel,
    PipeModel,
    SpatialRelationshipModel,
    TextModel,
    TitleBlockFieldModel,
    TitleBlockModel,
)
from src.normalizer.schema import (
    BlockAttribute,
    BlockDefinition,
    CADEntity,
    DimensionEntity,
    Drawing,
    DrawingFrame,
    EquipmentInfo,
    Layer,
    LayoutInfo,
    ParseResult,
    PipeInfo,
    SpatialRelationship,
    TextEntity,
    TitleBlock,
)
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.database.repo")


def _to_json(value: Any) -> str:
    """Serialize value to JSON string."""
    if value is None:
        return "null"
    if isinstance(value, (tuple, list)):
        return json.dumps(list(value))
    return json.dumps(value)


def _from_json(value: str | None) -> Any:
    """Deserialize JSON string."""
    if value is None or value == "null":
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


class DrawingRepository:
    """Repository for drawing-related database operations."""

    def __init__(self, session: Session | None = None):
        self.session = session or get_session()

    def find_by_hash(self, file_hash: str) -> DrawingModel | None:
        """Check if a drawing with the given hash already exists."""
        return (
            self.session.query(DrawingModel)
            .filter(DrawingModel.file_hash == file_hash)
            .first()
        )

    def find_by_id(self, drawing_id: str) -> DrawingModel | None:
        return (
            self.session.query(DrawingModel)
            .filter(DrawingModel.drawing_id == drawing_id)
            .first()
        )

    def update_thumbnail_path(self, drawing_id: str, thumbnail_path: str) -> None:
        """Update the thumbnail path for a drawing."""
        d = self.find_by_id(drawing_id)
        if d:
            d.thumbnail_path = thumbnail_path
            self.session.commit()

    def list_drawings(self, limit: int = 100, offset: int = 0) -> list[DrawingModel]:
        return (
            self.session.query(DrawingModel)
            .order_by(DrawingModel.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def delete_drawing(self, drawing_id: str) -> bool:
        """Delete a drawing and all its child rows."""
        # Child tables without ORM cascade need explicit deletes.
        child_models = [
            LayerModel,
            BlockDefModel,
            LayoutModel,
            EntityModel,
            TextModel,
            DimensionModel,
            BlockAttributeModel,
            DrawingFrameModel,
            TitleBlockModel,
            TitleBlockFieldModel,
            EquipmentModel,
            PipeModel,
            SpatialRelationshipModel,
            ParseLogModel,
        ]
        for model in child_models:
            self.session.query(model).filter(
                getattr(model, "drawing_id") == drawing_id
            ).delete(synchronize_session=False)

        draw = self.session.query(DrawingModel).filter(
            DrawingModel.drawing_id == drawing_id
        ).first()
        if draw:
            self.session.delete(draw)
            self.session.commit()
            logger.info(f"已删除图纸: {drawing_id}")
            return True
        return False

    def count_drawings(self) -> int:
        return self.session.query(DrawingModel).count()

    def save_parse_result(self, result: ParseResult, overwrite: bool = False) -> str:
        """Save a complete ParseResult to the database.

        Args:
            result: ParseResult from the parser.
            overwrite: If True and the hash already exists, delete the
                old record (including child rows) before saving.

        Returns:
            drawing_id of the saved drawing.
        """
        drawing = result.drawing
        drawing_id = drawing.drawing_id

        # Check for existing drawing (duplicate)
        existing = self.find_by_hash(drawing.file_hash)
        if existing:
            if not overwrite:
                logger.info(f"文件已存在(重复): {drawing.file_name} (hash={drawing.file_hash[:16]}...)")
                return existing.drawing_id
            logger.info(f"覆盖重新导入: {drawing.file_name} (删除旧记录 {existing.drawing_id[:8]}...)")
            self.delete_drawing(existing.drawing_id)

        # Save drawing
        draw_model = DrawingModel(
            drawing_id=drawing_id,
            file_name=drawing.file_name,
            file_path=drawing.file_path,
            file_hash=drawing.file_hash,
            file_size=drawing.file_size,
            file_type=drawing.file_type.value if hasattr(drawing.file_type, 'value') else str(drawing.file_type),
            cad_version=drawing.cad_version,
            cad_version_name=drawing.cad_version_name,
            units=drawing.units,
            insunits=drawing.insunits,
            created_time=drawing.created_time,
            modified_time=drawing.modified_time,
            parser=drawing.parser,
            parser_version=drawing.parser_version,
            parse_status=drawing.parse_status.value if hasattr(drawing.parse_status, 'value') else str(drawing.parse_status),
            parse_time=drawing.parse_time,
            entity_count=drawing.entity_count,
            text_count=drawing.text_count,
            dimension_count=drawing.dimension_count,
            layer_count=drawing.layer_count,
            block_count=drawing.block_count,
            layout_count=drawing.layout_count,
            data_completeness=drawing.data_completeness,
            thumbnail_path=drawing.thumbnail_path,
            raw_data_path=drawing.raw_data_path,
            notes=drawing.notes,
        )
        self.session.add(draw_model)

        # Save layers
        for layer in result.layers:
            self._save_layer(layer, drawing_id)

        # Save block definitions
        for block in result.blocks:
            self._save_block(block, drawing_id)

        # Save layouts
        for layout in result.layouts:
            self._save_layout(layout, drawing_id)

        # Save entities
        entity_id_map = {}  # Map schema entity_id → ORM entity (for FK references)
        for entity in result.entities:
            ent_model = self._save_entity(entity, drawing_id)
            if ent_model:
                entity_id_map[entity.entity_id] = ent_model

        # Save texts
        for txt in result.texts:
            self._save_text(txt, drawing_id)

        # Save dimensions
        for dim in result.dimensions:
            self._save_dimension(dim, drawing_id)

        # Save block attributes
        for attrib in result.attributes:
            self._save_attribute(attrib, drawing_id)

        # Save semantic analysis results (Phase 3)
        for frame in result.frames:
            self._save_frame(frame, drawing_id)

        for tb in result.title_blocks:
            self._save_title_block(tb, drawing_id)

        for eq in result.equipment:
            self._save_equipment(eq, drawing_id)

        for pipe in result.pipes:
            self._save_pipe(pipe, drawing_id)

        # Save spatial relationships (Phase 4)
        for rel in result.relationships:
            self._save_relationship(rel, drawing_id)

        # Save parse log entries
        for err in result.errors:
            self._save_log(drawing_id, "ERROR", "parse", err.get("error", str(err)), err)

        for warn in result.warnings:
            self._save_log(drawing_id, "WARNING", "parse", str(warn), warn)

        # Update FTS indexes
        self._update_fts(drawing_id, result)

        self.session.commit()
        logger.info(
            f"图纸已保存: {drawing.file_name} "
            f"(entities={drawing.entity_count}, texts={drawing.text_count}, "
            f"dims={drawing.dimension_count})"
        )

        return drawing_id

    def _save_layer(self, layer: Layer, drawing_id: str):
        model = LayerModel(
            layer_id=layer.layer_id,
            drawing_id=drawing_id,
            name=layer.name,
            color=layer.color,
            linetype=layer.linetype,
            lineweight=layer.lineweight,
            is_on=layer.is_on,
            is_frozen=layer.is_frozen,
            is_locked=layer.is_locked,
            entity_count=layer.entity_count,
        )
        self.session.add(model)

    def _save_block(self, block: BlockDefinition, drawing_id: str):
        model = BlockDefModel(
            block_id=block.block_id,
            drawing_id=drawing_id,
            name=block.name,
            base_point=_to_json(list(block.base_point)),
            is_anonymous=block.is_anonymous,
            is_layout=block.is_layout,
            entity_count=block.entity_count,
            has_attributes=block.has_attributes,
            source_file=block.source_file,
        )
        self.session.add(model)

    def _save_layout(self, layout: LayoutInfo, drawing_id: str):
        model = LayoutModel(
            layout_id=layout.layout_id,
            drawing_id=drawing_id,
            name=layout.name,
            layout_type=layout.layout_type,
            tab_order=layout.tab_order,
            viewport_count=layout.viewport_count,
            entity_count=layout.entity_count,
            plot_settings=_to_json(layout.plot_settings),
        )
        self.session.add(model)

    def _save_entity(self, entity: CADEntity, drawing_id: str) -> EntityModel | None:
        bbox = entity.bounding_box
        model = EntityModel(
            entity_id=entity.entity_id,
            drawing_id=drawing_id,
            handle=entity.handle,
            entity_type=entity.entity_type,
            layer=entity.layer,
            layout=entity.layout,
            space=entity.space.value if hasattr(entity.space, 'value') else str(entity.space),
            block_name=entity.block_name,
            color=entity.color,
            linetype=entity.linetype,
            lineweight=entity.lineweight,
            bbox_min_x=bbox.min_x,
            bbox_min_y=bbox.min_y,
            bbox_min_z=bbox.min_z,
            bbox_max_x=bbox.max_x,
            bbox_max_y=bbox.max_y,
            bbox_max_z=bbox.max_z,
            coordinates=_to_json(entity.coordinates),
            properties=_to_json(entity.properties),
            source_file=entity.source_file,
            source_handle=entity.source_handle,
            source_layer=entity.source_layer,
            data_tier=entity.data_tier.value if hasattr(entity.data_tier, 'value') else str(entity.data_tier),
        )
        self.session.add(model)
        return model

    def _save_text(self, txt: TextEntity, drawing_id: str):
        model = TextModel(
            text_id=txt.text_id,
            entity_id=txt.entity_id,
            drawing_id=drawing_id,
            text_content=txt.text_content,
            raw_text=txt.raw_text,
            position=_to_json(list(txt.position)),
            rotation=txt.rotation,
            height=txt.height,
            text_type=txt.text_type,
            style=txt.style,
            width_factor=txt.width_factor,
            layer=txt.layer,
            layout=txt.layout,
            block_name=txt.block_name,
            handle=txt.handle,
        )
        self.session.add(model)

    def _save_dimension(self, dim: DimensionEntity, drawing_id: str):
        model = DimensionModel(
            dimension_id=dim.dimension_id,
            entity_id=dim.entity_id,
            drawing_id=drawing_id,
            dimension_type=dim.dimension_type,
            measurement=dim.measurement,
            text_content=dim.text_content,
            defpoint1=_to_json(list(dim.defpoint1)),
            defpoint2=_to_json(list(dim.defpoint2)),
            defpoint3=_to_json(list(dim.defpoint3)),
            dimline_point=_to_json(list(dim.dimline_point)),
            style=dim.style,
            rotation=dim.rotation,
            layer=dim.layer,
            layout=dim.layout,
            handle=dim.handle,
        )
        self.session.add(model)

    def _save_attribute(self, attrib: BlockAttribute, drawing_id: str):
        model = BlockAttributeModel(
            attrib_id=attrib.attrib_id,
            drawing_id=drawing_id,
            insert_entity_id=attrib.insert_entity_id,
            block_name=attrib.block_name,
            tag=attrib.tag,
            value=attrib.value,
            position=_to_json(list(attrib.position)),
            height=attrib.height,
            rotation=attrib.rotation,
            layer=attrib.layer,
            insert_position=_to_json(list(attrib.insert_position)),
            handle=attrib.handle,
        )
        self.session.add(model)

    # ── Semantic analysis persistence (Phase 3) ────────────────────

    def _save_frame(self, frame: DrawingFrame, drawing_id: str):
        model = DrawingFrameModel(
            frame_id=frame.frame_id,
            drawing_id=drawing_id,
            min_x=frame.bounding_box.min_x,
            min_y=frame.bounding_box.min_y,
            max_x=frame.bounding_box.max_x,
            max_y=frame.bounding_box.max_y,
            width=frame.bounding_box.width,
            height=frame.bounding_box.height,
            layer=frame.layer,
            handle=frame.handle,
            entity_count=frame.entity_count,
            source=frame.source,
            confidence=frame.confidence,
        )
        self.session.add(model)

    def _save_title_block(self, tb: TitleBlock, drawing_id: str):
        model = TitleBlockModel(
            title_block_id=tb.title_block_id,
            drawing_id=drawing_id,
            min_x=tb.bounding_box.min_x,
            min_y=tb.bounding_box.min_y,
            max_x=tb.bounding_box.max_x,
            max_y=tb.bounding_box.max_y,
            width=tb.bounding_box.width,
            height=tb.bounding_box.height,
            layer=tb.layer,
            confidence=tb.confidence,
            source=tb.source,
        )
        self.session.add(model)

        for field in tb.fields:
            self._save_title_block_field(field, drawing_id, tb.title_block_id)

    def _save_title_block_field(self, field, drawing_id: str, title_block_id: str):
        model = TitleBlockFieldModel(
            field_id=field.field_id,
            drawing_id=drawing_id,
            title_block_id=title_block_id,
            key=field.key,
            value=field.value,
            raw_key=field.raw_key,
            layer=field.layer,
            handle=field.handle,
            x=field.x,
            y=field.y,
            confidence=field.confidence,
            source=field.source,
        )
        self.session.add(model)

    def _save_equipment(self, eq: EquipmentInfo, drawing_id: str):
        model = EquipmentModel(
            equipment_id=eq.equipment_id,
            drawing_id=drawing_id,
            equipment_no=eq.equipment_no,
            equipment_name=eq.equipment_name,
            block_name=eq.block_name,
            layer=eq.layer,
            handle=eq.handle,
            x=eq.x,
            y=eq.y,
            attributes=_to_json(eq.attributes),
            confidence=eq.confidence,
            source=eq.source,
        )
        self.session.add(model)

    def _save_pipe(self, pipe: PipeInfo, drawing_id: str):
        model = PipeModel(
            pipe_id=pipe.pipe_id,
            drawing_id=drawing_id,
            pipe_no=pipe.pipe_no,
            diameter=pipe.diameter,
            material=pipe.material,
            layer=pipe.layer,
            handle=pipe.handle,
            x=pipe.x,
            y=pipe.y,
            confidence=pipe.confidence,
            source=pipe.source,
        )
        self.session.add(model)

    def _save_relationship(self, rel: SpatialRelationship, drawing_id: str):
        model = SpatialRelationshipModel(
            rel_id=rel.rel_id,
            drawing_id=drawing_id,
            entity_a_id=rel.entity_a_id,
            entity_b_id=rel.entity_b_id,
            relationship_type=rel.relationship_type.value
            if hasattr(rel.relationship_type, "value")
            else str(rel.relationship_type),
            distance=rel.distance,
            confidence=rel.confidence,
            source=rel.source,
        )
        self.session.add(model)

    def _save_log(
        self, drawing_id: str, level: str, operation: str,
        message: str, details: dict,
    ):
        import uuid
        model = ParseLogModel(
            log_id=str(uuid.uuid4()),
            drawing_id=drawing_id,
            timestamp=datetime.now(),
            level=level,
            operation=operation,
            message=message,
            details=_to_json(details),
        )
        self.session.add(model)

    def _update_fts(self, drawing_id: str, result: ParseResult):
        """Update FTS5 full-text indexes."""
        # Texts FTS
        for txt in result.texts:
            try:
                self.session.execute(text(
                    "INSERT INTO texts_fts (text_content, drawing_id, entity_id, layer, layout) "
                    "VALUES (:content, :did, :eid, :layer, :layout)"
                ), {
                    "content": txt.text_content,
                    "did": drawing_id,
                    "eid": txt.entity_id,
                    "layer": txt.layer,
                    "layout": txt.layout,
                })
            except Exception as e:
                logger.warning(f"FTS texts 插入失败: {e}")

        # Attributes FTS
        for attrib in result.attributes:
            try:
                self.session.execute(text(
                    "INSERT INTO attributes_fts (tag, value, drawing_id, block_name) "
                    "VALUES (:tag, :value, :did, :bname)"
                ), {
                    "tag": attrib.tag,
                    "value": attrib.value,
                    "did": drawing_id,
                    "bname": attrib.block_name,
                })
            except Exception as e:
                logger.warning(f"FTS attributes 插入失败: {e}")

        # Drawings FTS
        try:
            self.session.execute(text(
                "INSERT INTO drawings_fts (file_name, notes, drawing_id) "
                "VALUES (:fname, :notes, :did)"
            ), {
                "fname": result.drawing.file_name,
                "notes": result.drawing.notes or "",
                "did": drawing_id,
            })
        except Exception as e:
            logger.warning(f"FTS drawings 插入失败: {e}")

    # ─── Query Methods ───────────────────────────────────────────────

    def get_drawing_summary(self, drawing_id: str) -> dict | None:
        """Get a summary dict for a drawing."""
        draw = self.find_by_id(drawing_id)
        if not draw:
            return None
        return {
            "drawing_id": draw.drawing_id,
            "file_name": draw.file_name,
            "file_type": draw.file_type,
            "cad_version": draw.cad_version,
            "cad_version_name": draw.cad_version_name,
            "parse_status": draw.parse_status,
            "entity_count": draw.entity_count,
            "text_count": draw.text_count,
            "dimension_count": draw.dimension_count,
            "layer_count": draw.layer_count,
            "block_count": draw.block_count,
            "data_completeness": draw.data_completeness,
            "parse_time": draw.parse_time.isoformat() if draw.parse_time else None,
        }

    def get_entities_by_drawing(
        self, drawing_id: str,
        entity_type: str | None = None,
        layer: str | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        """Get entities for a drawing, optionally filtered."""
        query = (
            self.session.query(EntityModel)
            .filter(EntityModel.drawing_id == drawing_id)
        )
        if entity_type:
            query = query.filter(EntityModel.entity_type == entity_type.upper())
        if layer:
            query = query.filter(EntityModel.layer == layer)

        entities = query.limit(limit).all()
        return [
            {
                "entity_id": e.entity_id,
                "handle": e.handle,
                "entity_type": e.entity_type,
                "layer": e.layer,
                "layout": e.layout,
                "block_name": e.block_name,
                "bbox": {
                    "min_x": e.bbox_min_x, "min_y": e.bbox_min_y,
                    "max_x": e.bbox_max_x, "max_y": e.bbox_max_y,
                },
                "properties": _from_json(e.properties),
                "data_tier": e.data_tier,
            }
            for e in entities
        ]

    def get_texts_by_drawing(self, drawing_id: str, limit: int = 500) -> list[dict]:
        texts = (
            self.session.query(TextModel)
            .filter(TextModel.drawing_id == drawing_id)
            .limit(limit)
            .all()
        )
        return [
            {
                "text_id": t.text_id,
                "text_content": t.text_content,
                "text_type": t.text_type,
                "layer": t.layer,
                "handle": t.handle,
                "height": t.height,
                "position": _from_json(t.position),
            }
            for t in texts
        ]

    def get_dimensions_by_drawing(self, drawing_id: str, limit: int = 500) -> list[dict]:
        dims = (
            self.session.query(DimensionModel)
            .filter(DimensionModel.drawing_id == drawing_id)
            .limit(limit)
            .all()
        )
        return [
            {
                "dimension_id": d.dimension_id,
                "dimension_type": d.dimension_type,
                "measurement": d.measurement,
                "text_content": d.text_content,
                "layer": d.layer,
                "handle": d.handle,
            }
            for d in dims
        ]

    # ── Semantic queries (Phase 3) ─────────────────────────────────

    def get_frames_by_drawing(self, drawing_id: str) -> list[dict]:
        """Get recognized drawing frames for a drawing."""
        rows = (
            self.session.query(DrawingFrameModel)
            .filter(DrawingFrameModel.drawing_id == drawing_id)
            .all()
        )
        return [
            {
                "frame_id": r.frame_id,
                "width": r.width,
                "height": r.height,
                "min_x": r.min_x,
                "min_y": r.min_y,
                "layer": r.layer,
                "confidence": r.confidence,
                "entity_count": r.entity_count,
                "source": r.source,
            }
            for r in rows
        ]

    def get_title_blocks_by_drawing(self, drawing_id: str) -> list[dict]:
        """Get title blocks (with fields) for a drawing."""
        blocks = (
            self.session.query(TitleBlockModel)
            .filter(TitleBlockModel.drawing_id == drawing_id)
            .all()
        )
        out = []
        for b in blocks:
            fields = (
                self.session.query(TitleBlockFieldModel)
                .filter(TitleBlockFieldModel.title_block_id == b.title_block_id)
                .all()
            )
            out.append({
                "title_block_id": b.title_block_id,
                "width": b.width,
                "height": b.height,
                "layer": b.layer,
                "confidence": b.confidence,
                "fields": [
                    {
                        "key": f.key,
                        "value": f.value,
                        "raw_key": f.raw_key,
                        "layer": f.layer,
                        "confidence": f.confidence,
                    }
                    for f in fields
                ],
            })
        return out

    def get_equipment_by_drawing(self, drawing_id: str) -> list[dict]:
        """Get recognized equipment for a drawing."""
        rows = (
            self.session.query(EquipmentModel)
            .filter(EquipmentModel.drawing_id == drawing_id)
            .all()
        )
        return [
            {
                "equipment_id": r.equipment_id,
                "equipment_no": r.equipment_no,
                "equipment_name": r.equipment_name,
                "block_name": r.block_name,
                "layer": r.layer,
                "x": r.x,
                "y": r.y,
                "attributes": _from_json(r.attributes),
                "confidence": r.confidence,
                "source": r.source,
            }
            for r in rows
        ]

    def get_pipes_by_drawing(self, drawing_id: str) -> list[dict]:
        """Get recognized pipes for a drawing."""
        rows = (
            self.session.query(PipeModel)
            .filter(PipeModel.drawing_id == drawing_id)
            .all()
        )
        return [
            {
                "pipe_id": r.pipe_id,
                "pipe_no": r.pipe_no,
                "diameter": r.diameter,
                "material": r.material,
                "layer": r.layer,
                "x": r.x,
                "y": r.y,
                "confidence": r.confidence,
                "source": r.source,
            }
            for r in rows
        ]

    def get_relationships_by_drawing(
        self,
        drawing_id: str,
        rel_type: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        """Get spatial relationships for a drawing.

        Args:
            drawing_id: The drawing's ID.
            rel_type: Optional relationship type filter (e.g. "near").
            limit: Max rows.

        Returns:
            List of dicts, each with entity ids, types and distance.
        """
        q = self.session.query(SpatialRelationshipModel).filter(
            SpatialRelationshipModel.drawing_id == drawing_id
        )
        if rel_type:
            q = q.filter(SpatialRelationshipModel.relationship_type == rel_type)
        rows = q.limit(limit).all()

        # Build entity type lookup for human-readable output
        entity_types: dict[str, str] = {}
        eids = {r.entity_a_id for r in rows} | {r.entity_b_id for r in rows}
        if eids:
            ents = (
                self.session.query(EntityModel.entity_id, EntityModel.entity_type)
                .filter(EntityModel.entity_id.in_(eids))
                .all()
            )
            entity_types = {eid: etype for eid, etype in ents}

        return [
            {
                "rel_id": r.rel_id,
                "entity_a_id": r.entity_a_id,
                "entity_b_id": r.entity_b_id,
                "entity_a_type": entity_types.get(r.entity_a_id, ""),
                "entity_b_type": entity_types.get(r.entity_b_id, ""),
                "relationship_type": r.relationship_type,
                "distance": r.distance,
                "confidence": r.confidence,
                "source": r.source,
            }
            for r in rows
        ]

    def search_fulltext(self, query_str: str, limit: int = 50) -> list[dict]:
        """Full-text search across texts."""
        try:
            results = self.session.execute(text(
                "SELECT text_content, drawing_id, entity_id, layer, layout "
                "FROM texts_fts WHERE text_content MATCH :q "
                "LIMIT :limit"
            ), {"q": query_str, "limit": limit}).fetchall()

            return [
                {
                    "text_content": r[0],
                    "drawing_id": r[1],
                    "entity_id": r[2],
                    "layer": r[3],
                    "layout": r[4],
                }
                for r in results
            ]
        except Exception as e:
            logger.error(f"全文搜索失败: {e}")
            return []

    def _fast_count(self, table_name: str) -> int:
        """Fast row count approximation using MAX(rowid).

        For tables without deletions this equals COUNT(*). It is orders of
        magnitude faster on multi-million-row SQLite tables because it uses
        the rowid B-tree instead of a full table scan.
        """
        try:
            result = self.session.execute(
                text(f"SELECT MAX(rowid) FROM {table_name}")
            ).scalar()
            return result or 0
        except Exception:
            return 0

    def get_database_stats(self) -> dict:
        """Get database statistics (fast rowid-based counts)."""
        return {
            "drawings": self._fast_count("drawings"),
            "entities": self._fast_count("entities"),
            "texts": self._fast_count("texts"),
            "dimensions": self._fast_count("dimensions"),
            "layers": self._fast_count("layers"),
            "blocks": self._fast_count("block_defs"),
            "attributes": self._fast_count("block_attributes"),
            "frames": self._fast_count("drawing_frames"),
            "title_blocks": self._fast_count("title_blocks"),
            "title_block_fields": self._fast_count("title_block_fields"),
            "equipment": self._fast_count("equipment"),
            "pipes": self._fast_count("pipes"),
            "relationships": self._fast_count("spatial_relationships"),
        }
