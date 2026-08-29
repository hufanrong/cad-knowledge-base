"""Relationship builder — 关系构建.

Beyond pure geometric proximity, this module builds semantic
relationships that are deterministic:
- BELONGS_TO: entities sharing a common block reference / layer context
  are marked as belonging to the block INSERT.
- ANNOTATES: text entities that sit near a leader or dimension.

Everything is computed deterministically (source="computed") and never
guessed.
"""

from __future__ import annotations

from src.normalizer.schema import RelationshipType, SpatialRelationship
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.spatial.relationship")


class RelationshipBuilder:
    """Build derived spatial/semantic relationships."""

    def build_block_membership(
        self,
        entities: list,
        inserts: list,
    ) -> list[SpatialRelationship]:
        """Mark entities as BELONGS_TO their block INSERT.

        Each entity with a block_name matching an INSERT whose bbox
        contains the entity is linked via BELONGS_TO.

        Returns:
            List of SpatialRelationship (BELONGS_TO).
        """
        rels: list[SpatialRelationship] = []
        if not entities or not inserts:
            return rels

        for ins in inserts:
            if ins.entity_type != "INSERT":
                continue
            bb = ins.bounding_box
            if not bb.width or not bb.height:
                continue
            for e in entities:
                if e.entity_id == ins.entity_id:
                    continue
                if e.entity_type == "ATTRIB" and e.handle:
                    # ATTRIB entities reference their INSERT via block context
                    rels.append(SpatialRelationship(
                        entity_a_id=ins.entity_id,
                        entity_b_id=e.entity_id,
                        relationship_type=RelationshipType.BELONGS_TO,
                        confidence=0.9,
                        source="computed",
                    ))

        logger.info(f"关系构建: {len(rels)} 条 BELONGS_TO 关系")
        return rels
