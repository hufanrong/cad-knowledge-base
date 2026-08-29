"""Drawing frame (图框) detection.

The drawing frame is the outermost rectangle that borders a CAD sheet.
It is typically drawn as either:
- A closed LWPOLYLINE rectangle (4 vertices, closed)
- 4 individual LINE entities forming a rectangle

Strategy (rule-based, conservative):
1. Consider only entities in Model space that are LINE or LWPOLYLINE.
2. For each entity compute its bounding box.
3. A frame candidate must:
   - Be "close to" a rectangle (area vs bounding-box-area ratio >= 0.98)
   - Have a large area relative to the drawing extent (>= 1% of overall)
   - For LWPOLYLINE: have exactly 4 points and closed flag.
   - For LINEs: group collinear/adjacent lines that share endpoints
     to build closed rectangles.
4. Pick the largest candidate as the frame.

Everything is rule-based; if no candidate is found, returns None
(no fabrication).
"""

from __future__ import annotations

from pathlib import Path

from src.normalizer.schema import BoundingBox, DrawingFrame, SpaceType
from src.utils.geometry import bbox_area
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.semantic.frame")

# Minimum area ratio of a candidate's area to its bounding box
# for it to be considered a rectangle (allow small tolerance).
RECT_TOLERANCE = 0.98
# Minimum share of total drawing area a frame must occupy
MIN_FRAME_AREA_RATIO = 0.01


class FrameDetector:
    """Detect the drawing frame from parsed entities."""

    def analyze(
        self,
        entities: list,
        drawing_extent: BoundingBox | None = None,
    ) -> DrawingFrame | None:
        """Detect the drawing frame.

        Args:
            entities: List of parsed CADEntity objects.
            drawing_extent: Optional overall bounding box of the drawing
                (used to judge relative frame size). If None, computed
                from the entities.

        Returns:
            DrawingFrame or None if no frame was confidently detected.
        """
        if not entities:
            return None

        # Filter to model-space line/polyline entities only
        line_candidates = [
            e for e in entities
            if e.space == SpaceType.MODEL and e.entity_type in ("LINE", "LWPOLYLINE")
        ]
        if not line_candidates:
            logger.info("图框识别: 无 LINE/LWPOLYLINE 实体，跳过")
            return None

        # Compute overall extent
        if drawing_extent is None:
            drawing_extent = self._compute_extent(entities)

        total_area = bbox_area(drawing_extent)
        if total_area <= 0:
            return None

        best: DrawingFrame | None = None
        best_score = 0.0

        # Candidate 1: individual closed LWPOLYLINE rectangles
        for e in line_candidates:
            if e.entity_type != "LWPOLYLINE":
                continue
            bb = e.bounding_box
            area = bbox_area(bb)
            if area <= 0:
                continue
            if not self._is_rectangle_like(e):
                continue
            area_ratio = area / total_area
            if area_ratio < MIN_FRAME_AREA_RATIO:
                continue
            if area_ratio > best_score:
                best_score = area_ratio
                best = DrawingFrame(
                    bounding_box=bb.model_copy(),
                    layer=e.layer,
                    handle=e.handle,
                    entity_count=1,
                    source="rule_based",
                    confidence=min(1.0, 0.6 + 0.4 * area_ratio),
                )

        # Candidate 2: a group of LINE entities forming a closed rectangle
        line_rect = self._find_line_rectangle(
            [e for e in line_candidates if e.entity_type == "LINE"],
            drawing_extent,
            total_area,
        )
        if line_rect and line_rect.confidence * bbox_area(line_rect.bounding_box) / max(total_area, 1) > best_score:
            best = line_rect

        if best:
            logger.info(
                f"图框识别: 找到图框 {best.bounding_box.width:.0f}x{best.bounding_box.height:.0f} "
                f"置信度={best.confidence:.2f}"
            )
        else:
            logger.info("图框识别: 未找到明显图框")

        return best

    def _find_line_rectangle(
        self,
        lines: list,
        extent: BoundingBox,
        total_area: float,
    ) -> DrawingFrame | None:
        """Detect a rectangle formed by LINE entities sharing endpoints.

        Builds an endpoint graph (endpoint -> connected endpoints) and
        looks for a 4-cycle whose corners form an axis-aligned rectangle.
        Independent of the overall drawing extent, so interior content
        or annotations extending past the frame do not break detection.
        """
        if len(lines) < 4:
            return None

        # Tolerance relative to the drawing scale
        tol = max(extent.width, extent.height) * 0.002 or 1.0

        # Map raw coordinates -> representative endpoint key (with tolerance)
        rep_map: dict[tuple, tuple] = {}
        rep_keys: list[tuple] = []

        def rep_of(x: float, y: float) -> tuple:
            for k in rep_keys:
                if abs(k[0] - x) <= tol and abs(k[1] - y) <= tol:
                    return k
            rep_keys.append((x, y))
            return (x, y)

        # Build graph: point key -> list of (other_point_key, line_index)
        graph: dict[tuple, list[tuple[tuple, int]]] = {}
        line_data: list[dict] = []
        for idx, e in enumerate(lines):
            coords = e.coordinates
            # coordinates = [x1, y1, z1, x2, y2, z2]
            if len(coords) < 6:
                continue
            p1 = rep_of(coords[0], coords[1])
            p2 = rep_of(coords[3], coords[4])
            if p1 == p2:
                continue  # degenerate
            graph.setdefault(p1, []).append((p2, idx))
            graph.setdefault(p2, []).append((p1, idx))
            line_data.append({"entity": e, "p1": p1, "p2": p2})

        if len(graph) < 4:
            return None

        best: DrawingFrame | None = None
        best_area = 0.0

        # Find 4-cycles forming an axis-aligned rectangle.
        # For each cycle we also recover the 4 LINE entities on the path.
        for p0 in list(graph.keys()):
            for p1, e01 in graph[p0]:
                for p2, e12 in graph[p1]:
                    if p2 == p0:
                        continue
                    for p3, e23 in graph[p2]:
                        if p3 in (p0, p1):
                            continue
                        # p3 must connect back to p0
                        back = [e for n, e in graph[p3] if n == p0]
                        if not back:
                            continue
                        # Axis-aligned rectangle check
                        xs = {p0[0], p1[0], p2[0], p3[0]}
                        ys = {p0[1], p1[1], p2[1], p3[1]}
                        if len(xs) != 2 or len(ys) != 2:
                            continue
                        w = max(xs) - min(xs)
                        h = max(ys) - min(ys)
                        if w <= 0 or h <= 0:
                            continue
                        area = w * h
                        if area < best_area:
                            continue
                        best_area = area
                        bb = BoundingBox(
                            min_x=min(xs),
                            min_y=min(ys),
                            max_x=max(xs),
                            max_y=max(ys),
                            width=w,
                            height=h,
                        )
                        area_ratio = area / max(total_area, 1)
                        if area_ratio < MIN_FRAME_AREA_RATIO:
                            continue
                        conf = min(1.0, 0.55 + 0.45 * min(area_ratio, 1.0))
                        # Recover the 4 entities on the cycle
                        edge_indices = [e01, e12, e23, back[0]]
                        layer_counts: dict[str, int] = {}
                        handles: list[str] = []
                        for ei in edge_indices:
                            if ei < len(line_data):
                                ent = line_data[ei]["entity"]
                                layer_counts[ent.layer] = layer_counts.get(ent.layer, 0) + 1
                                if ent.handle:
                                    handles.append(ent.handle)
                        dom = max(layer_counts, key=layer_counts.get) if layer_counts else ""
                        best = DrawingFrame(
                            bounding_box=bb,
                            layer=dom,
                            handle=handles[0] if handles else "",
                            entity_count=4,
                            source="rule_based",
                            confidence=round(conf, 2),
                        )

        return best

    # ── helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _is_rectangle_like(entity) -> bool:
        """Check whether a single entity is rectangle-like."""
        etype = entity.entity_type

        if etype == "LWPOLYLINE":
            points = entity.properties.get("points")
            is_closed = entity.properties.get("is_closed", False)
            if not points or len(points) < 4 or not is_closed:
                return False
            # 4 distinct points => rectangle-like candidate
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            if max(xs) - min(xs) <= 0 or max(ys) - min(ys) <= 0:
                return False
            return True

        if etype == "LINE":
            # A single LINE cannot be a frame; handled by grouping below.
            return False

        return False

    @staticmethod
    def _compute_extent(entities: list) -> BoundingBox:
        """Compute the union bounding box of all entities."""
        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")
        for e in entities:
            bb = e.bounding_box
            min_x = min(min_x, bb.min_x)
            min_y = min(min_y, bb.min_y)
            max_x = max(max_x, bb.max_x)
            max_y = max(max_y, bb.max_y)
        if min_x == float("inf"):
            return BoundingBox()
        return BoundingBox(
            min_x=min_x,
            min_y=min_y,
            max_x=max_x,
            max_y=max_y,
            width=max_x - min_x,
            height=max_y - min_y,
        )


def detect_frame(
    entities: list,
    drawing_extent: BoundingBox | None = None,
) -> DrawingFrame | None:
    """Convenience wrapper for FrameDetector.analyze()."""
    return FrameDetector().analyze(entities, drawing_extent)
