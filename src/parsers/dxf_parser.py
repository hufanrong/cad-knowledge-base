"""DXF Parser based on ezdxf.

This parser reads DXF files using the ezdxf library and converts
all entities into the unified CAD data schema.

Key principles:
- All data from the file is tagged as DataTier.NORMALIZED
- Derived data (computed lengths, areas) is tagged as DataTier.DERIVED
- Nothing is guessed or fabricated
- MTEXT formatting codes are stripped for clean text, raw text preserved
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf.entities import DXFGraphic
from ezdxf.layouts import Modelspace, Paperspace

from src.normalizer.schema import (
    BoundingBox,
    BlockAttribute,
    BlockDefinition,
    CADEntity,
    DataTier,
    DimensionEntity,
    Drawing,
    FileType,
    LayoutInfo,
    Layer,
    ParseResult,
    QualityReport,
    SpaceType,
    TextEntity,
    ViewportInfo,
)
from src.parsers.base_parser import BaseParser
from src.utils.geometry import (
    arc_endpoints,
    arc_length,
    bbox_from_center_radius,
    bbox_intersects,
    compute_bbox_from_points,
    line_angle,
    line_length,
)
from src.utils.logger import setup_logger
from src.utils.units import detect_units

logger = setup_logger("cadkb.parsers.dxf")

# Dimension type codes from ezdxf/dxf spec
DIMENSION_TYPES = {
    0: "linear",
    1: "aligned",
    2: "angular",
    3: "diameter",
    4: "radius",
    5: "angular3p",
    6: "ordinate",
}


class DXFParser(BaseParser):
    """Parse DXF files using ezdxf."""

    def __init__(self):
        self._strip_mtext = True
        self._save_raw_mtext = True

    @property
    def name(self) -> str:
        return "ezdxf"

    @property
    def version(self) -> str:
        return f"ezdxf-{ezdxf.__version__}"

    @property
    def supported_types(self) -> list[str]:
        return ["dxf"]

    def can_parse(self, file_path: str | Path) -> bool:
        path = Path(file_path)
        return path.suffix.lower() == ".dxf"

    def parse(self, file_path: str | Path) -> ParseResult:
        """Parse a DXF file and return structured data."""
        path = Path(file_path)
        logger.info(f"开始解析 DXF: {path.name}")

        result = ParseResult()

        try:
            doc = ezdxf.readfile(str(path))
        except Exception as e:
            logger.error(f"DXF 解析失败: {path.name} - {e}")
            result.drawing = Drawing(
                file_name=path.name,
                file_path=str(path.absolute()),
                parse_status="failed",
                parser=self.name,
                parser_version=self.version,
            )
            result.errors.append({
                "operation": "readfile",
                "error": str(e),
                "file": str(path),
            })
            return result

        # Extract header variables (access specific ones we need)
        header = {}
        for varname in ["$ACADVER", "$INSUNITS", "$DWGCODEPAGE", "$MEASUREMENT",
                        "$LUNITS", "$LUPREC", "$AUNITS", "$EXTMIN", "$EXTMAX"]:
            try:
                header[varname] = doc.header[varname]
            except Exception:
                pass
        cad_version = header.get("$ACADVER", "")
        units, insunits = detect_units(header)

        # Initialize drawing record
        result.drawing = Drawing(
            file_name=path.name,
            file_path=str(path.absolute()),
            file_type=FileType.DXF,
            cad_version=cad_version,
            cad_version_name=_version_name(cad_version),
            units=units,
            insunits=insunits,
            parser=self.name,
            parser_version=self.version,
            parse_status="success",
            parse_time=datetime.now(),
        )

        drawing_id = result.drawing.drawing_id

        # 1. Extract layers
        for layer in doc.layers:
            result.layers.append(self._normalize_layer(layer, drawing_id))
        logger.info(f"  图层数: {len(result.layers)}")

        # 2. Extract block definitions
        for block in doc.blocks:
            # Skip layout blocks and anonymous blocks for separate handling
            bd = self._normalize_block(block, drawing_id, path.name)
            if bd:
                result.blocks.append(bd)
        logger.info(f"  块定义: {len(result.blocks)}")

        # 3. Extract layouts
        for layout in doc.layouts:
            li = self._normalize_layout(layout, drawing_id)
            result.layouts.append(li)
        logger.info(f"  布局数: {len(result.layouts)}")

        # 4. Extract entities from model space
        msp = doc.modelspace()
        for entity in msp:
            self._process_entity(
                entity, result, drawing_id, path.name,
                layout="Model", space=SpaceType.MODEL,
            )

        # 5. Extract entities from paper space layouts
        for layout in doc.layouts:
            if layout.name == "Model":
                continue
            for entity in layout:
                self._process_entity(
                    entity, result, drawing_id, path.name,
                    layout=layout.name, space=SpaceType.PAPER,
                )

        logger.info(f"  实体总数: {len(result.entities)}")
        logger.info(f"  文字数: {len(result.texts)}")
        logger.info(f"  尺寸数: {len(result.dimensions)}")
        logger.info(f"  块属性: {len(result.attributes)}")

        # 6. Generate quality report
        result.quality_report = self._build_quality_report(result)
        result.drawing.entity_count = len(result.entities)
        result.drawing.text_count = len(result.texts)
        result.drawing.dimension_count = len(result.dimensions)
        result.drawing.layer_count = len(result.layers)
        result.drawing.block_count = len(result.blocks)
        result.drawing.layout_count = len(result.layouts)
        result.drawing.data_completeness = result.quality_report.data_completeness

        logger.info(
            f"  解析完成: {result.drawing.parse_status}, "
            f"完整度={result.drawing.data_completeness:.1%}"
        )

        return result

    # ─── Layer ───────────────────────────────────────────────────────

    def _normalize_layer(self, layer, drawing_id: str) -> Layer:
        return Layer(
            drawing_id=drawing_id,
            name=layer.dxf.name,
            color=layer.dxf.color if layer.dxf.color else 7,
            linetype=layer.dxf.linetype or "Continuous",
            lineweight=getattr(layer.dxf, "lineweight", -2),
            is_on=layer.is_on(),
            is_frozen=layer.is_frozen(),
            is_locked=layer.is_locked(),
        )

    # ─── Block ───────────────────────────────────────────────────────

    def _normalize_block(
        self, block, drawing_id: str, source_file: str
    ) -> BlockDefinition | None:
        name = block.name
        if not name:
            return None

        is_layout = name.startswith("*Paper_Space") or name.startswith("*Model_Space")
        is_anon = name.startswith("*")

        # Count entities in block
        try:
            entity_count = len(list(block))
        except Exception:
            entity_count = 0

        # Check for attribute definitions
        has_attrs = any(e.dxftype() == "ATTDEF" for e in block)

        return BlockDefinition(
            drawing_id=drawing_id,
            name=name,
            base_point=(
                block.base_point[0] if block.base_point else 0.0,
                block.base_point[1] if block.base_point else 0.0,
                block.base_point[2] if len(block.base_point) > 2 else 0.0,
            ),
            is_anonymous=is_anon,
            is_layout=is_layout,
            entity_count=entity_count,
            has_attributes=has_attrs,
            source_file=source_file,
        )

    # ─── Layout ──────────────────────────────────────────────────────

    def _normalize_layout(self, layout, drawing_id: str) -> LayoutInfo:
        is_model = layout.name == "Model" or layout.is_modelspace
        try:
            entity_count = len(list(layout))
        except Exception:
            entity_count = 0

        return LayoutInfo(
            drawing_id=drawing_id,
            name=layout.name,
            layout_type="model" if is_model else "paper",
            tab_order=layout.dxf.taborder if hasattr(layout.dxf, "taborder") else 0,
            entity_count=entity_count,
        )

    # ─── Entity Processing ───────────────────────────────────────────

    def _process_entity(
        self,
        entity: DXFGraphic,
        result: ParseResult,
        drawing_id: str,
        source_file: str,
        layout: str,
        space: SpaceType,
    ):
        """Process a single DXF entity and add it to the result."""
        try:
            etype = entity.dxftype().upper()

            # Skip layout-related entities
            if etype in ("BLOCK", "ENDBLK"):
                return

            # Get common properties
            dxf = entity.dxf
            handle = dxf.handle if hasattr(dxf, "handle") else ""
            layer_name = dxf.layer if hasattr(dxf, "layer") else "0"
            color = dxf.color if hasattr(dxf, "color") and dxf.color else 256
            linetype = dxf.linetype if hasattr(dxf, "linetype") else "BYLAYER"
            lineweight = dxf.lineweight if hasattr(dxf, "lineweight") else -2

            # Build entity based on type
            entity_data = self._extract_entity_data(entity, etype)
            if entity_data is None:
                result.warnings.append({
                    "entity_type": etype,
                    "handle": handle,
                    "message": f"Unsupported entity type: {etype}",
                })
                return

            # Compute bounding box
            bbox = self._compute_bbox(entity, etype, entity_data)

            # Flatten coordinates
            coords = self._flatten_coords(entity_data.get("points", []))

            # Create unified entity
            cad_entity = CADEntity(
                drawing_id=drawing_id,
                handle=handle,
                entity_type=etype,
                layer=layer_name,
                layout=layout,
                space=space,
                color=color,
                linetype=linetype,
                lineweight=lineweight,
                bounding_box=bbox,
                coordinates=coords,
                properties=entity_data.get("properties", {}),
                source_file=source_file,
                source_handle=handle,
                source_layer=layer_name,
                data_tier=DataTier.NORMALIZED,
            )

            # For INSERT entities, set block_name
            if etype == "INSERT":
                cad_entity.block_name = entity_data.get("properties", {}).get("block_name", "")

            result.entities.append(cad_entity)

            # Handle special entity types
            if etype in ("TEXT", "MTEXT"):
                text_entity = self._extract_text(entity, etype, drawing_id, handle, layer_name, layout, cad_entity.entity_id)
                if text_entity:
                    result.texts.append(text_entity)

            elif etype == "DIMENSION":
                dim_entity = self._extract_dimension(entity, drawing_id, handle, layer_name, layout, cad_entity.entity_id)
                if dim_entity:
                    result.dimensions.append(dim_entity)

            elif etype == "INSERT":
                # Extract block attributes
                attribs = self._extract_attributes(entity, drawing_id, cad_entity.entity_id, source_file)
                result.attributes.extend(attribs)

        except Exception as e:
            result.errors.append({
                "entity_type": entity.dxftype() if hasattr(entity, "dxftype") else "Unknown",
                "handle": str(entity.dxf.handle) if hasattr(entity.dxf, "handle") else "",
                "error": str(e),
            })
            logger.warning(f"  实体解析失败: {etype} handle={handle} - {e}")

    # ─── Entity Data Extraction ──────────────────────────────────────

    def _extract_entity_data(self, entity, etype: str) -> dict | None:
        """Extract type-specific data from an entity.
        
        Returns dict with 'points' (list of coordinate tuples) and
        'properties' (dict of type-specific attributes).
        """
        dxf = entity.dxf

        if etype == "LINE":
            start = tuple(dxf.start)[:3] if dxf.start else (0, 0, 0)
            end = tuple(dxf.end)[:3] if dxf.end else (0, 0, 0)
            length = line_length(start, end)
            angle = line_angle(start, end)
            return {
                "points": [start, end],
                "properties": {
                    "start": list(start),
                    "end": list(end),
                    "length": length,
                    "angle": round(angle, 4),
                },
            }

        elif etype == "CIRCLE":
            center = tuple(dxf.center)[:3] if dxf.center else (0, 0, 0)
            radius = dxf.radius if dxf.radius else 0
            circumference = 2 * math.pi * radius
            area = math.pi * radius ** 2
            return {
                "points": [center],
                "properties": {
                    "center": list(center),
                    "radius": radius,
                    "circumference": round(circumference, 4),
                    "area": round(area, 4),
                },
            }

        elif etype == "ARC":
            center = tuple(dxf.center)[:3] if dxf.center else (0, 0, 0)
            radius = dxf.radius if dxf.radius else 0
            start_angle = dxf.start_angle if hasattr(dxf, "start_angle") else 0
            end_angle = dxf.end_angle if hasattr(dxf, "end_angle") else 0
            a_len = arc_length(radius, start_angle, end_angle)
            return {
                "points": [center],
                "properties": {
                    "center": list(center),
                    "radius": radius,
                    "start_angle": round(start_angle, 4),
                    "end_angle": round(end_angle, 4),
                    "arc_length": round(a_len, 4),
                },
            }

        elif etype == "LWPOLYLINE":
            points = []
            try:
                for x, y, *_ in entity.get_points():
                    points.append((x, y, 0.0))
            except Exception:
                pts = dxf.points if hasattr(dxf, "points") else []
                for p in pts:
                    points.append(tuple(p)[:3])
            closed = dxf.closed if hasattr(dxf, "closed") else False
            return {
                "points": points,
                "properties": {
                    "vertices": [list(p) for p in points],
                    "closed": bool(closed),
                    "vertex_count": len(points),
                },
            }

        elif etype == "POLYLINE":
            points = []
            try:
                for v in entity.vertices:
                    points.append(tuple(v.dxf.location)[:3])
            except Exception:
                pass
            closed = dxf.is_closed if hasattr(dxf, "is_closed") else False
            return {
                "points": points,
                "properties": {
                    "vertices": [list(p) for p in points],
                    "closed": bool(closed),
                    "vertex_count": len(points),
                },
            }

        elif etype == "SPLINE":
            ctrl_points = []
            fit_points = []
            try:
                ctrl_points = [tuple(p)[:3] for p in entity.control_points]
            except Exception:
                pass
            try:
                fit_points = [tuple(p)[:3] for p in entity.fit_points]
            except Exception:
                pass
            return {
                "points": ctrl_points or fit_points,
                "properties": {
                    "control_points": [list(p) for p in ctrl_points],
                    "fit_points": [list(p) for p in fit_points],
                    "degree": dxf.degree if hasattr(dxf, "degree") else 3,
                },
            }

        elif etype == "ELLIPSE":
            center = tuple(dxf.center)[:3] if dxf.center else (0, 0, 0)
            major_axis = tuple(dxf.major_axis)[:3] if hasattr(dxf, "major_axis") and dxf.major_axis else (1, 0, 0)
            ratio = dxf.ratio if hasattr(dxf, "ratio") else 1.0
            start_param = dxf.start_param if hasattr(dxf, "start_param") else 0.0
            end_param = dxf.end_param if hasattr(dxf, "end_param") else 2 * math.pi
            return {
                "points": [center],
                "properties": {
                    "center": list(center),
                    "major_axis": list(major_axis),
                    "ratio": ratio,
                    "start_param": start_param,
                    "end_param": end_param,
                },
            }

        elif etype == "TEXT":
            text = dxf.text if hasattr(dxf, "text") else ""
            insert = tuple(dxf.insert)[:3] if dxf.insert else (0, 0, 0)
            height = dxf.height if hasattr(dxf, "height") else 0
            rotation = dxf.rotation if hasattr(dxf, "rotation") else 0
            return {
                "points": [insert],
                "properties": {
                    "text": text,
                    "position": list(insert),
                    "height": height,
                    "rotation": round(rotation, 4),
                },
            }

        elif etype == "MTEXT":
            raw_text = dxf.text if hasattr(dxf, "text") else ""
            clean_text = self._strip_mtext_codes(raw_text)
            insert = tuple(dxf.insert)[:3] if dxf.insert else (0, 0, 0)
            height = dxf.char_height if hasattr(dxf, "char_height") else 0
            rotation = dxf.rotation if hasattr(dxf, "rotation") else 0
            width = dxf.width if hasattr(dxf, "width") else 0
            return {
                "points": [insert],
                "properties": {
                    "text": clean_text,
                    "raw_text": raw_text if self._save_raw_mtext else "",
                    "position": list(insert),
                    "height": height,
                    "rotation": round(rotation, 4),
                    "width": width,
                },
            }

        elif etype == "DIMENSION":
            # Dimension entity — extract what we can
            dimtype = dxf.dimtype if hasattr(dxf, "dimtype") else 0
            dim_type_name = DIMENSION_TYPES.get(dimtype & 0x7, "unknown")
            measurement = 0.0
            try:
                measurement = entity.get_measurement() if hasattr(entity, "get_measurement") else 0.0
            except Exception:
                pass
            text = dxf.text if hasattr(dxf, "text") else ""

            defpoint1 = tuple(dxf.defpoint)[:3] if hasattr(dxf, "defpoint") and dxf.defpoint else (0, 0, 0)
            defpoint2 = tuple(dxf.defpoint2)[:3] if hasattr(dxf, "defpoint2") and dxf.defpoint2 else (0, 0, 0)
            defpoint3 = tuple(dxf.defpoint3)[:3] if hasattr(dxf, "defpoint3") and dxf.defpoint3 else (0, 0, 0)
            dimline = tuple(dxf.defpoint4)[:3] if hasattr(dxf, "defpoint4") and dxf.defpoint4 else (0, 0, 0)
            style = dxf.dimstyle if hasattr(dxf, "dimstyle") else ""
            rotation = dxf.angle if hasattr(dxf, "angle") else 0

            return {
                "points": [defpoint1, defpoint2, defpoint3],
                "properties": {
                    "dimension_type": dim_type_name,
                    "measurement": measurement,
                    "text": text,
                    "defpoint1": list(defpoint1),
                    "defpoint2": list(defpoint2),
                    "defpoint3": list(defpoint3),
                    "dimline_point": list(dimline),
                    "style": style,
                    "rotation": round(rotation, 4),
                },
            }

        elif etype == "LEADER":
            points = []
            try:
                points = [tuple(p)[:3] for p in entity.vertices]
            except Exception:
                pass
            return {
                "points": points,
                "properties": {
                    "vertices": [list(p) for p in points],
                    "vertex_count": len(points),
                },
            }

        elif etype == "HATCH":
            # Extract boundary paths
            paths = []
            try:
                for path in entity.paths:
                    path_vertices = []
                    if hasattr(path, "vertices"):
                        path_vertices = [list(v)[:3] for v in path.vertices]
                    paths.append({"vertices": path_vertices, "type": str(type(path).__name__)})
            except Exception:
                pass
            pattern = dxf.pattern_name if hasattr(dxf, "pattern_name") else ""
            return {
                "points": [],
                "properties": {
                    "pattern": pattern,
                    "path_count": len(paths),
                    "paths": paths,
                },
            }

        elif etype == "INSERT":
            block_name = dxf.name if hasattr(dxf, "name") else ""
            insert_pt = tuple(dxf.insert)[:3] if dxf.insert else (0, 0, 0)
            sx = dxf.xscale if hasattr(dxf, "xscale") else 1.0
            sy = dxf.yscale if hasattr(dxf, "yscale") else 1.0
            sz = dxf.zscale if hasattr(dxf, "zscale") else 1.0
            rotation = dxf.rotation if hasattr(dxf, "rotation") else 0.0
            return {
                "points": [insert_pt],
                "properties": {
                    "block_name": block_name,
                    "insert_point": list(insert_pt),
                    "scale_x": sx,
                    "scale_y": sy,
                    "scale_z": sz,
                    "rotation": round(rotation, 4),
                },
            }

        elif etype == "POINT":
            location = tuple(dxf.location)[:3] if hasattr(dxf, "location") and dxf.location else (0, 0, 0)
            return {
                "points": [location],
                "properties": {
                    "position": list(location),
                },
            }

        elif etype == "VIEWPORT":
            center = tuple(dxf.center)[:3] if hasattr(dxf, "center") and dxf.center else (0, 0, 0)
            width = dxf.width if hasattr(dxf, "width") else 0
            height = dxf.height if hasattr(dxf, "height") else 0
            return {
                "points": [center],
                "properties": {
                    "center": list(center),
                    "width": width,
                    "height": height,
                },
            }

        else:
            # Unknown/proxy entity — save raw data
            return {
                "points": [],
                "properties": {
                    "raw_data": str(dxf),
                    "note": f"Unsupported entity type: {etype}",
                },
            }

    # ─── Bounding Box ────────────────────────────────────────────────

    def _compute_bbox(self, entity, etype: str, data: dict) -> BoundingBox:
        """Compute bounding box for an entity."""
        points = data.get("points", [])

        if etype in ("CIRCLE", "ARC"):
            props = data.get("properties", {})
            center = props.get("center", [0, 0, 0])
            radius = props.get("radius", 0)
            return bbox_from_center_radius(
                center[0], center[1],
                center[2] if len(center) > 2 else 0,
                radius,
            )

        if etype == "ELLIPSE":
            props = data.get("properties", {})
            center = props.get("center", [0, 0, 0])
            major = props.get("major_axis", [1, 0, 0])
            ratio = props.get("ratio", 1.0)
            major_len = math.sqrt(sum(c ** 2 for c in major))
            minor_len = major_len * ratio
            max_r = max(major_len, minor_len)
            return bbox_from_center_radius(center[0], center[1], center[2] if len(center) > 2 else 0, max_r)

        if etype == "INSERT":
            # Use insertion point as a degenerate bbox
            props = data.get("properties", {})
            insert = props.get("insert_point", [0, 0, 0])
            return BoundingBox(
                min_x=insert[0], min_y=insert[1], min_z=insert[2] if len(insert) > 2 else 0,
                max_x=insert[0], max_y=insert[1], max_z=insert[2] if len(insert) > 2 else 0,
                width=0, height=0,
            )

        # Default: compute from points
        if points:
            return compute_bbox_from_points(points)

        return BoundingBox()

    # ─── Text Extraction ─────────────────────────────────────────────

    def _extract_text(
        self, entity, etype: str, drawing_id: str, handle: str,
        layer: str, layout: str, entity_id: str,
    ) -> TextEntity | None:
        """Extract text entity for full-text search."""
        dxf = entity.dxf

        if etype == "TEXT":
            text = dxf.text if hasattr(dxf, "text") else ""
            insert = tuple(dxf.insert)[:3] if dxf.insert else (0, 0, 0)
            height = dxf.height if hasattr(dxf, "height") else 0
            rotation = dxf.rotation if hasattr(dxf, "rotation") else 0
            style = dxf.style if hasattr(dxf, "style") else ""
            width_factor = dxf.width if hasattr(dxf, "width") else 1.0
        else:  # MTEXT
            raw_text = dxf.text if hasattr(dxf, "text") else ""
            text = self._strip_mtext_codes(raw_text)
            insert = tuple(dxf.insert)[:3] if dxf.insert else (0, 0, 0)
            height = dxf.char_height if hasattr(dxf, "char_height") else 0
            rotation = dxf.rotation if hasattr(dxf, "rotation") else 0
            style = dxf.style if hasattr(dxf, "style") else ""
            width_factor = 1.0

        return TextEntity(
            entity_id=entity_id,
            drawing_id=drawing_id,
            text_content=text,
            raw_text=raw_text if etype == "MTEXT" else text,
            position=insert,
            rotation=round(rotation, 4),
            height=height,
            text_type=etype,
            style=style,
            width_factor=width_factor,
            layer=layer,
            layout=layout,
            handle=handle,
        )

    # ─── Dimension Extraction ────────────────────────────────────────

    def _extract_dimension(
        self, entity, drawing_id: str, handle: str,
        layer: str, layout: str, entity_id: str,
    ) -> DimensionEntity | None:
        """Extract dimension entity."""
        dxf = entity.dxf
        dimtype = dxf.dimtype if hasattr(dxf, "dimtype") else 0
        dim_type_name = DIMENSION_TYPES.get(dimtype & 0x7, "unknown")

        measurement = 0.0
        try:
            measurement = entity.get_measurement() if hasattr(entity, "get_measurement") else 0.0
        except Exception:
            pass

        text = dxf.text if hasattr(dxf, "text") else ""

        defpoint1 = tuple(dxf.defpoint)[:3] if hasattr(dxf, "defpoint") and dxf.defpoint else (0, 0, 0)
        defpoint2 = tuple(dxf.defpoint2)[:3] if hasattr(dxf, "defpoint2") and dxf.defpoint2 else (0, 0, 0)
        defpoint3 = tuple(dxf.defpoint3)[:3] if hasattr(dxf, "defpoint3") and dxf.defpoint3 else (0, 0, 0)
        dimline = tuple(dxf.defpoint4)[:3] if hasattr(dxf, "defpoint4") and dxf.defpoint4 else (0, 0, 0)
        style = dxf.dimstyle if hasattr(dxf, "dimstyle") else ""
        rotation = dxf.angle if hasattr(dxf, "angle") else 0

        return DimensionEntity(
            entity_id=entity_id,
            drawing_id=drawing_id,
            dimension_type=dim_type_name,
            measurement=measurement,
            text_content=text,
            defpoint1=defpoint1,
            defpoint2=defpoint2,
            defpoint3=defpoint3,
            dimline_point=dimline,
            style=style,
            rotation=round(rotation, 4),
            layer=layer,
            layout=layout,
            handle=handle,
        )

    # ─── Block Attribute Extraction ──────────────────────────────────

    def _extract_attributes(
        self, entity, drawing_id: str, insert_entity_id: str,
        source_file: str,
    ) -> list[BlockAttribute]:
        """Extract block attributes from an INSERT entity."""
        attribs = []
        try:
            if not hasattr(entity, "attribs"):
                return attribs

            insert_pt = tuple(entity.dxf.insert)[:3] if entity.dxf.insert else (0, 0, 0)
            block_name = entity.dxf.name if hasattr(entity.dxf, "name") else ""

            for attrib in entity.attribs:
                dxf = attrib.dxf
                attrib_entity = BlockAttribute(
                    drawing_id=drawing_id,
                    insert_entity_id=insert_entity_id,
                    block_name=block_name,
                    tag=dxf.tag if hasattr(dxf, "tag") else "",
                    value=dxf.text if hasattr(dxf, "text") else "",
                    position=tuple(dxf.insert)[:3] if dxf.insert else (0, 0, 0),
                    height=dxf.height if hasattr(dxf, "height") else 0,
                    rotation=dxf.rotation if hasattr(dxf, "rotation") else 0,
                    layer=dxf.layer if hasattr(dxf, "layer") else "0",
                    insert_position=insert_pt,
                    handle=dxf.handle if hasattr(dxf, "handle") else "",
                )
                attribs.append(attrib_entity)
        except Exception as e:
            logger.warning(f"  块属性提取失败: {e}")

        return attribs

    # ─── MTEXT Code Stripping ────────────────────────────────────────

    @staticmethod
    def _strip_mtext_codes(text: str) -> str:
        """Remove MTEXT formatting codes to get clean text.
        
        MTEXT uses codes like \\P (paragraph), \\A (alignment),
        {\\f (font), \\C (color), etc.
        """
        if not text:
            return ""

        # Remove formatting codes
        # \\P → newline
        text = text.replace("\\P", "\n")
        # \\n → newline
        text = text.replace("\\n", "\n")
        # Remove {\\fCode;...} font commands
        text = re.sub(r"\{\\[^;]+;", "", text)
        # Remove \\A, \\C, \\H, \\W, \\Q, \\T, \\S codes
        text = re.sub(r"\\[ACfHhWwQqTsS\.;0-9\-\.,/\\\(\)]+", "", text)
        # Remove remaining braces
        text = text.replace("{", "").replace("}", "")
        # Remove \\~ (non-breaking space)
        text = text.replace("\\~", " ")
        # Remove backslash escapes
        text = re.sub(r"\\[\\{}]", lambda m: m.group(0)[1], text)
        # Clean up multiple newlines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    # ─── Quality Report ──────────────────────────────────────────────

    def _build_quality_report(self, result: ParseResult) -> QualityReport:
        """Build data quality report from parse results."""
        report = QualityReport(
            entity_count=len(result.entities),
            text_count=len(result.texts),
            dimension_count=len(result.dimensions),
            layer_count=len(result.layers),
            block_count=len(result.blocks),
            layout_count=len(result.layouts),
            attribute_count=len(result.attributes),
            parse_errors=len(result.errors),
            parse_warnings=len(result.warnings),
            coordinate_issues=0,
            unit_detected=result.drawing.units != "unknown",
        )

        # Check for coordinate issues
        for ent in result.entities:
            if ent.bounding_box.width == 0 and ent.bounding_box.height == 0:
                if ent.entity_type not in ("POINT", "INSERT", "TEXT", "MTEXT"):
                    report.coordinate_issues += 1

        # Completeness calculation
        checks = []

        # Entity check
        if report.entity_count > 0:
            checks.append(True)
            report.checks_passed.append("entity_count > 0")
        else:
            checks.append(False)
            report.checks_failed.append("entity_count == 0")

        # Layer check
        if report.layer_count > 0:
            checks.append(True)
            report.checks_passed.append("layer_count > 0")
        else:
            checks.append(False)
            report.checks_failed.append("layer_count == 0")

        # Unit check
        if report.unit_detected:
            checks.append(True)
            report.checks_passed.append("unit_detected")
        else:
            checks.append(False)
            report.checks_failed.append("unit_not_detected")

        # Error rate check
        if report.entity_count > 0:
            error_rate = report.parse_errors / report.entity_count
            if error_rate < 0.05:
                checks.append(True)
                report.checks_passed.append(f"error_rate={error_rate:.1%} < 5%")
            else:
                checks.append(False)
                report.checks_failed.append(f"error_rate={error_rate:.1%} >= 5%")
        else:
            checks.append(False)
            report.checks_failed.append("no entities to check")

        # Text extraction check
        if report.entity_count > 0:
            text_types = sum(1 for e in result.entities if e.entity_type in ("TEXT", "MTEXT"))
            if text_types > 0 and report.text_count == text_types:
                checks.append(True)
                report.checks_passed.append("all texts extracted")
            elif text_types == 0:
                checks.append(True)
                report.checks_passed.append("no texts in drawing")
            else:
                checks.append(False)
                report.checks_failed.append(f"texts: found={text_types}, extracted={report.text_count}")

        # Completeness = ratio of passed checks
        report.data_completeness = sum(checks) / len(checks) if checks else 0.0

        return report

    # ─── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _flatten_coords(points: list[tuple[float, ...]]) -> list[float]:
        """Flatten a list of coordinate tuples into a single list."""
        result = []
        for p in points:
            result.extend(list(p)[:3])
            # Pad to 3D
            while len(result) % 3 != 0:
                result.append(0.0)
        return result


def _version_name(version_code: str) -> str:
    """Get human-readable version name from code."""
    from src.normalizer.schema import DWG_VERSION_MAP
    return DWG_VERSION_MAP.get(
        version_code.encode("ascii", errors="replace"),
        f"Unknown ({version_code})",
    )
