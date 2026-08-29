"""Spatial analysis orchestration (Phase 4).

Runs the spatial relationship pipeline on a ParseResult:
1. Proximity analysis: CONTAINS / INTERSECTS / NEAR between entities
2. Annotation detection: text near entities -> ANNOTATES
3. Block membership: ATTRIB entities -> BELONGS_TO their INSERT

All outputs are deterministic (source="computed") with confidence.
"""

from __future__ import annotations

from src.normalizer.schema import ParseResult
from src.spatial.proximity import ProximityAnalyzer
from src.spatial.relationship import RelationshipBuilder
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.spatial.analyzer")


class SpatialAnalyzer:
    """Orchestrates spatial analysis on a parsed drawing."""

    def __init__(self, near_threshold: float = 100.0, max_pairs: int = 2000):
        self.proximity = ProximityAnalyzer(
            near_threshold=near_threshold,
            max_pairs=max_pairs,
        )
        self.builder = RelationshipBuilder()

    def analyze(self, result: ParseResult) -> ParseResult:
        """Run all spatial analyses, mutating and returning the result."""
        if result.drawing.parse_status != "success":
            logger.info("空间分析: 解析未成功，跳过")
            return result

        drawing_id = result.drawing.drawing_id
        logger.info(f"开始空间分析: {result.drawing.file_name}")

        # Entities that can participate in spatial relations
        model_entities = [
            e for e in result.entities
            if e.entity_id
        ]

        # 1. Geometric relationships (contains/intersects/near)
        geo_rels = self.proximity.analyze(model_entities)

        # 2. Text annotations
        ann_rels = self.proximity.find_annotations(result.texts, model_entities)

        # 3. Block membership (ATTRIB -> INSERT)
        inserts = [e for e in model_entities if e.entity_type == "INSERT"]
        block_rels = self.builder.build_block_membership(model_entities, inserts)

        # Merge, tag drawing_id, dedupe by (a, b, type)
        seen: set[tuple] = set()
        for rel in geo_rels + ann_rels + block_rels:
            rel.drawing_id = drawing_id
            key = (rel.entity_a_id, rel.entity_b_id, rel.relationship_type.value if hasattr(rel.relationship_type, "value") else str(rel.relationship_type))
            if key in seen:
                continue
            seen.add(key)
            result.relationships.append(rel)

        logger.info(
            f"空间分析完成: 共 {len(result.relationships)} 条关系 "
            f"(几何={len(geo_rels)}, 标注={len(ann_rels)}, 块归属={len(block_rels)})"
        )
        return result


def analyze(result: ParseResult, near_threshold: float = 100.0) -> ParseResult:
    """Convenience wrapper for SpatialAnalyzer().analyze()."""
    return SpatialAnalyzer(near_threshold=near_threshold).analyze(result)
