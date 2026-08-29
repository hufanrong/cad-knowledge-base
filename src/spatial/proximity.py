"""Proximity analysis — 邻近分析.

Determines whether entities are near each other in space, and if so
records the pairwise distance. Uses bounding boxes with a configurable
distance threshold.

All results are deterministic (source="computed"), confidence reflects
how much closer the entities are than the threshold.
"""

from __future__ import annotations

from src.normalizer.schema import BoundingBox, RelationshipType, SpatialRelationship
from src.utils.geometry import bbox_contains, bbox_distance, bbox_intersects
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.spatial.proximity")


class ProximityAnalyzer:
    """Find near/interesecting/containing entity pairs."""

    def __init__(self, near_threshold: float = 100.0, max_pairs: int = 2000):
        """Initialize.

        Args:
            near_threshold: Maximum distance (drawing units) to consider
                two entities "near" each other.
            max_pairs: Cap on relationships per drawing to avoid blowup.
        """
        self.near_threshold = near_threshold
        self.max_pairs = max_pairs

    def analyze(self, entities: list) -> list[SpatialRelationship]:
        """Compute spatial relationships among entities.

        Args:
            entities: List of CADEntity (schema models, each with a
                bounding_box and entity_id).

        Returns:
            List of SpatialRelationship.
        """
        if len(entities) < 2:
            return []

        # Ignore zero-area entities (points, degenerate) for containment
        usable = [e for e in entities if e.entity_id and e.bounding_box.width > 0 and e.bounding_box.height > 0]
        if len(usable) < 2:
            return []

        rels: list[SpatialRelationship] = []
        n = len(usable)

        # O(n^2) but capped; spatial hash could be a later optimization.
        for i in range(n):
            if len(rels) >= self.max_pairs:
                break
            a = usable[i]
            for j in range(i + 1, n):
                if len(rels) >= self.max_pairs:
                    break
                b = usable[j]
                rel = self._relation_between(a, b)
                if rel:
                    rels.append(rel)

        logger.info(f"空间关系: 计算 {len(rels)} 条关系（实体 {len(usable)} 个）")
        return rels

    def _relation_between(self, a, b) -> SpatialRelationship | None:
        """Compute the strongest relationship between two entities."""
        bb_a: BoundingBox = a.bounding_box
        bb_b: BoundingBox = b.bounding_box

        # 1. Containment — larger contains smaller
        if bbox_contains(bb_a, bb_b) and bbox_area_ratio(bb_b, bb_a) < 0.95:
            return SpatialRelationship(
                entity_a_id=a.entity_id,
                entity_b_id=b.entity_id,
                relationship_type=RelationshipType.CONTAINS,
                distance=bbox_distance(bb_a, bb_b),
                confidence=0.95,
                source="computed",
            )
        if bbox_contains(bb_b, bb_a) and bbox_area_ratio(bb_a, bb_b) < 0.95:
            return SpatialRelationship(
                entity_a_id=b.entity_id,
                entity_b_id=a.entity_id,
                relationship_type=RelationshipType.CONTAINS,
                distance=bbox_distance(bb_a, bb_b),
                confidence=0.95,
                source="computed",
            )

        # 2. Intersection
        if bbox_intersects(bb_a, bb_b):
            return SpatialRelationship(
                entity_a_id=a.entity_id,
                entity_b_id=b.entity_id,
                relationship_type=RelationshipType.INTERSECTS,
                distance=0.0,
                confidence=0.85,
                source="computed",
            )

        # 3. Near
        dist = bbox_distance(bb_a, bb_b)
        if dist <= self.near_threshold:
            conf = max(0.4, 1.0 - dist / max(self.near_threshold, 1e-9))
            return SpatialRelationship(
                entity_a_id=a.entity_id,
                entity_b_id=b.entity_id,
                relationship_type=RelationshipType.NEAR,
                distance=round(dist, 3),
                confidence=round(conf, 3),
                source="computed",
            )

        return None

    def find_annotations(
        self,
        texts: list,
        entities: list,
        max_distance: float | None = None,
    ) -> list[SpatialRelationship]:
        """Find text entities that annotate nearby drawing entities.

        A text is considered to annotate the nearest entity whose bbox is
        within max_distance (default: near_threshold).
        """
        if not texts or not entities:
            return []

        threshold = max_distance if max_distance is not None else self.near_threshold * 2
        rels: list[SpatialRelationship] = []

        for t in texts:
            t_pos = t.position
            best_dist = float("inf")
            best_e = None
            for e in entities:
                if not e.bounding_box.width and not e.bounding_box.height:
                    continue
                d = _point_bbox_distance(t_pos, e.bounding_box)
                if d < best_dist:
                    best_dist = d
                    best_e = e
            if best_e and best_dist <= threshold:
                rels.append(SpatialRelationship(
                    entity_a_id=t.entity_id,
                    entity_b_id=best_e.entity_id,
                    relationship_type=RelationshipType.ANNOTATES,
                    distance=round(best_dist, 3),
                    confidence=round(max(0.4, 1.0 - best_dist / max(threshold, 1e-9)), 3),
                    source="computed",
                ))
        return rels


def _point_bbox_distance(point: tuple, bb: BoundingBox) -> float:
    """Distance from a point to a bounding box."""
    px, py = point[0], point[1]
    dx = max(0.0, bb.min_x - px, px - bb.max_x)
    dy = max(0.0, bb.min_y - py, py - bb.max_y)
    return (dx * dx + dy * dy) ** 0.5


def bbox_area_ratio(inner: BoundingBox, outer: BoundingBox) -> float:
    """Ratio of inner bbox area to outer bbox area."""
    if not outer.width or not outer.height:
        return 0.0
    return (inner.width * inner.height) / (outer.width * outer.height)


def analyze_proximity(entities: list, near_threshold: float = 100.0) -> list[SpatialRelationship]:
    """Convenience wrapper for ProximityAnalyzer.analyze()."""
    return ProximityAnalyzer(near_threshold=near_threshold).analyze(entities)
