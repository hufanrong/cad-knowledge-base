"""Spatial analysis — 空间关系 (Phase 4).

Computes spatial relationships between entities:
- CONTAINS: entity A's bbox fully contains entity B's bbox
- INTERSECTS: two bboxes overlap
- NEAR: bboxes are close (within a threshold distance)
- ANNOTATES: a text/leader annotates a nearby entity
- BELONGS_TO: an ATTRIB belongs to its block INSERT

All relationships are computed deterministically (DataTier.DERIVED /
"computed"), with confidence derived from geometric certainty.
"""

from src.spatial.analyzer import SpatialAnalyzer, analyze
from src.spatial.proximity import ProximityAnalyzer, analyze_proximity
from src.spatial.relationship import RelationshipBuilder

__all__ = [
    "SpatialAnalyzer",
    "analyze",
    "ProximityAnalyzer",
    "analyze_proximity",
    "RelationshipBuilder",
]
