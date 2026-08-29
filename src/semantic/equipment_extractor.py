"""Equipment information extraction (设备信息识别).

Equipment in CAD drawings is usually represented as:
- INSERT blocks with ATTRIB attributes (e.g. EQUIP_NO, EQUIP_NAME)
- TEXT/MTEXT near a symbol naming the equipment

Strategy (rule-based):
1. Collect all INSERT entities with attributes. If attributes contain
   equipment-like tags (EQUIP_NO / 设备位号 / 位号 / EQUIP_NAME /
   设备名称 / 名称), build an EquipmentInfo from them.
2. Collect INSERT block names that look like equipment symbols
   (e.g. starting with a letter + digit, like "P101").
3. Fallback: text matching equipment name patterns near a block.

All results carry confidence. Empty values are NOT filled in.
"""

from __future__ import annotations

import re

from src.normalizer.schema import EquipmentInfo
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.semantic.equipment")

# Attribute tags commonly used for equipment identification
EQUIP_NO_TAGS = {"EQUIP_NO", "EQUIPNO", "位号", "设备位号", "设备编号"}
EQUIP_NAME_TAGS = {"EQUIP_NAME", "EQUIPNAME", "设备名称", "名称", "设备名"}

# Block name patterns that suggest equipment symbols
EQUIP_BLOCK_RE = re.compile(r"^[A-Za-z]{1,4}\d{1,4}$")

# Common equipment name keywords (Chinese) — used for text fallback
EQUIP_NAME_KEYWORDS = [
    "泵", "风机", "电机", "减速机", "搅拌", "反应", "换热", "冷却器",
    "分离器", "储罐", "罐", "塔", "磨机", "破碎", "窑", "输送", "皮带",
    "过滤", "压滤", "干燥", "除尘", "阀门", "阀", "汽轮机", "压缩机",
    "锅炉", "加热炉", "料仓", "仓", "振动筛", "筛",
]


class EquipmentExtractor:
    """Extract equipment information from parsed data."""

    def analyze(
        self,
        attributes: list,
        entities: list | None = None,
        texts: list | None = None,
    ) -> list[EquipmentInfo]:
        """Extract equipment from block attributes and entity hints.

        Args:
            attributes: List of BlockAttribute (from parser).
            entities: Optional list of CADEntity (for INSERT lookup).
            texts: Optional list of TextEntity (for name fallback).

        Returns:
            List of EquipmentInfo. Never fabricated — only items with
            at least a confident no/name are returned.
        """
        equipment: list[EquipmentInfo] = []
        seen_blocks: dict[str, dict] = {}  # block_name -> merged attrs

        # 1. Group attributes by their INSERT block (via insert_entity_id)
        for attr in attributes:
            key = (
                attr.insert_entity_id
                or f"{attr.handle}|{attr.layer}"
            )
            bucket = seen_blocks.setdefault(
                key,
                {"no": "", "name": "", "layer": attr.layer,
                 "block_name": attr.block_name or "", "handle": attr.handle,
                 "x": 0.0, "y": 0.0, "attrs": {}},
            )
            if attr.insert_position and len(attr.insert_position) >= 2:
                bucket["x"] = attr.insert_position[0]
                bucket["y"] = attr.insert_position[1]
            tag_upper = (attr.tag or "").strip().upper()
            value = (attr.value or "").strip()

            if tag_upper in {t.upper() for t in EQUIP_NO_TAGS}:
                if value and not bucket["no"]:
                    bucket["no"] = value
            elif tag_upper in {t.upper() for t in EQUIP_NAME_TAGS}:
                if value and not bucket["name"]:
                    bucket["name"] = value
            bucket["attrs"][attr.tag or ""] = value

        # 2. INSERT entities that look like equipment symbols
        if entities:
            for e in entities:
                if e.entity_type != "INSERT":
                    continue
                block_name = e.block_name or ""
                if EQUIP_BLOCK_RE.match(block_name):
                    key = e.entity_id
                    bucket = seen_blocks.setdefault(
                        key,
                        {"no": "", "name": "", "layer": e.layer,
                         "block_name": block_name, "handle": e.handle,
                         "x": 0.0, "y": 0.0, "attrs": {}},
                    )
                    coords = e.coordinates
                    if len(coords) >= 2:
                        bucket["x"] = coords[0]
                        bucket["y"] = coords[1]
                    if not bucket["name"] and self._looks_like_equipment_name(block_name):
                        bucket["name"] = block_name

        # 3. Build EquipmentInfo
        for key, bucket in seen_blocks.items():
            no = bucket["no"]
            name = bucket["name"]

            # Require at least one confident signal
            if not no and not name:
                continue

            conf = 0.0
            if no and name:
                conf = 0.9
            elif no:
                conf = 0.75
            elif name:
                conf = 0.6

            equipment.append(EquipmentInfo(
                equipment_no=no,
                equipment_name=name,
                block_name=bucket["block_name"],
                layer=bucket["layer"],
                handle=bucket["handle"],
                x=bucket.get("x", 0.0),
                y=bucket.get("y", 0.0),
                attributes=bucket["attrs"],
                confidence=round(conf, 2),
                source="rule_based",
            ))

        # 4. Text fallback: equipment-name keywords near no INSERT
        if texts and equipment == []:
            self._fallback_from_texts(texts, equipment)

        logger.info(f"设备识别: 找到 {len(equipment)} 个设备")
        return equipment

    def _fallback_from_texts(self, texts: list, equipment: list) -> None:
        """Very conservative fallback: only exact keyword-matched texts."""
        for t in texts:
            content = (t.text_content or "").strip()
            if not content:
                continue
            for kw in EQUIP_NAME_KEYWORDS:
                if content.endswith(kw) and len(content) <= 12:
                    equipment.append(EquipmentInfo(
                        equipment_name=content,
                        layer=t.layer,
                        handle=t.handle,
                        x=t.position[0],
                        y=t.position[1],
                        confidence=0.45,
                        source="rule_based",
                    ))
                    break

    @staticmethod
    def _looks_like_equipment_name(block_name: str) -> bool:
        """Block names like P101, PUMP-01 look like equipment."""
        return bool(EQUIP_BLOCK_RE.match(block_name))


def extract_equipment(
    attributes: list,
    entities: list | None = None,
    texts: list | None = None,
) -> list[EquipmentInfo]:
    """Convenience wrapper for EquipmentExtractor.analyze()."""
    return EquipmentExtractor().analyze(attributes, entities, texts)
