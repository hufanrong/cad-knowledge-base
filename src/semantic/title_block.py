"""Title block (标题栏) extraction.

The title block of a technical drawing is the structured table usually
located in the lower-right corner of the drawing frame. It contains
key-value information such as 图号 (drawing number), 图纸名称 (title),
比例 (scale), 设计单位 (design company), dates, and signatures.

Strategy (rule-based):
1. Given the drawing frame bbox, the title block is expected inside the
   lower-right area (e.g. lower 40% height, right 60% width).
2. Collect TEXT/MTEXT entities that fall inside that region.
3. Recognize key-value pairs: a "key" matches a known Chinese label
   (图号/图纸名称/比例/设计/审核/日期/共/张/第/页 etc.), and the
   "value" is text positioned to its right.

Results are AI_INFERENCE (rule_based) with confidence values. If a key
has no clear value, we record only the key with empty value — we never
invent a value.
"""

from __future__ import annotations

import re

from src.normalizer.schema import (
    BoundingBox,
    TitleBlock,
    TitleBlockField,
)
from src.utils.geometry import bbox_contains
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.semantic.title_block")

# Known Chinese label keys for title blocks (in priority order)
KNOWN_KEYS = {
    "图号": "图号",
    "图样名称": "图样名称",
    "图纸名称": "图纸名称",
    "图名": "图名",
    "名称": "名称",
    "比例": "比例",
    "设计": "设计",
    "制图": "制图",
    "校核": "校核",
    "审核": "审核",
    "审定": "审定",
    "批准": "批准",
    "日期": "日期",
    "共": "共",       # 共 X 张
    "第": "第",       # 第 X 张
    "页": "页",
    "张": "张",
    "工程名称": "工程名称",
    "项目名称": "项目名称",
    "设计单位": "设计单位",
    "单位": "单位",
    "材料": "材料",
    "重量": "重量",
    "数量": "数量",
}

# Region parameters for the title block (relative to frame)
TB_RIGHT_FRACTION = 0.6   # title block within right 60% of frame
TB_BOTTOM_FRACTION = 0.4  # within bottom 40% of frame


class TitleBlockExtractor:
    """Extract title block fields from parsed text entities."""

    def analyze(
        self,
        texts: list,
        frame_bbox: BoundingBox | None = None,
        entities: list | None = None,
    ) -> TitleBlock | None:
        """Extract the title block.

        Args:
            texts: List of TextEntity.
            frame_bbox: Bounding box of the recognized drawing frame.
                If None, the region is inferred from text positions only.
            entities: Optional full entity list (unused here but kept for
                API symmetry).

        Returns:
            TitleBlock or None.
        """
        if not texts:
            return None

        # Filter texts to the title-block region (if frame known)
        region_texts = self._texts_in_region(texts, frame_bbox)
        if not region_texts:
            return None

        # Build key-value pairs
        fields = self._extract_key_value_pairs(region_texts)

        # Region bbox: from the region texts
        region_bbox = self._bbox_of_texts(region_texts)

        if not fields:
            logger.info("标题栏: 区域内无已知键值文字")
            return None

        confidence = min(1.0, 0.5 + 0.1 * len(fields))
        tb = TitleBlock(
            bounding_box=region_bbox,
            layer=self._dominant_layer(region_texts),
            fields=fields,
            confidence=round(confidence, 2),
            source="rule_based",
        )
        logger.info(f"标题栏: 提取到 {len(fields)} 个字段，置信度={tb.confidence:.2f}")
        return tb

    # ── helpers ─────────────────────────────────────────────────────

    def _texts_in_region(self, texts: list, frame_bbox: BoundingBox | None) -> list:
        """Keep texts inside the title-block region."""
        if frame_bbox is None:
            # No frame info; assume all texts are candidates
            return list(texts)

        # Title block region: lower-right area of the frame
        tb_min_x = frame_bbox.min_x + frame_bbox.width * (1 - TB_RIGHT_FRACTION)
        tb_min_y = frame_bbox.min_y  # bottom
        region = BoundingBox(
            min_x=tb_min_x,
            min_y=tb_min_y,
            max_x=frame_bbox.max_x,
            max_y=frame_bbox.min_y + frame_bbox.height * TB_BOTTOM_FRACTION,
            width=frame_bbox.width * TB_RIGHT_FRACTION,
            height=frame_bbox.height * TB_BOTTOM_FRACTION,
        )

        inside = []
        for t in texts:
            x, y = t.position[0], t.position[1]
            if self._point_in_region(x, y, region):
                inside.append(t)
        return inside

    @staticmethod
    def _point_in_region(x: float, y: float, region: BoundingBox) -> bool:
        return (
            region.min_x <= x <= region.max_x
            and region.min_y <= y <= region.max_y
        )

    def _extract_key_value_pairs(self, texts: list) -> list[TitleBlockField]:
        """Recognize key-value pairs among region texts.

        A known key label found in a text may either:
        - Be followed by the value in the SAME text (e.g. "图号 2024-001")
        - Have the value in a SEPARATE text positioned to its right.
        """
        fields: list[TitleBlockField] = []
        used: set[int] = set()

        for i, t in enumerate(texts):
            content = (t.text_content or "").strip()
            if not content:
                continue

            matched_key = self._match_known_key(content)
            if matched_key is None:
                continue

            # Remove the key label to see if a value follows in same text
            rest = content.replace(matched_key, "", 1).strip()
            value = ""
            if rest:
                value = rest.strip(" :：")
                confidence = 0.8 if value else 0.4
            else:
                # Look for a value text positioned to the right
                value, confidence = self._find_value_to_right(texts, t, used)

            fields.append(TitleBlockField(
                key=matched_key,
                value=value,
                raw_key=content,
                layer=t.layer,
                handle=t.handle,
                x=t.position[0],
                y=t.position[1],
                confidence=round(confidence, 2),
                source="rule_based",
            ))
            if i in used:
                used.discard(i)

        return fields

    def _find_value_to_right(self, texts: list, key_text, used: set) -> tuple[str, float]:
        """Find a value text positioned to the right of the key text."""
        kx, ky = key_text.position[0], key_text.position[1]
        candidates = []
        for j, t in enumerate(texts):
            if j in used or t is key_text:
                continue
            content = (t.text_content or "").strip()
            if not content:
                continue
            if self._match_known_key(content) is not None:
                continue  # another key, not a value
            tx, ty = t.position[0], t.position[1]
            # Value: to the right, roughly same vertical level
            if tx > kx and abs(ty - ky) <= 20.0:
                candidates.append((tx - kx, j, content))

        if not candidates:
            return "", 0.3

        # nearest to the right
        candidates.sort()
        dist, j, content = candidates[0]
        used.add(j)
        conf = max(0.5, min(0.9, 0.7 - dist / 10000.0))
        return content, round(conf, 2)

    @staticmethod
    def _match_known_key(content: str) -> str | None:
        """Return the canonical key if content starts with a known label."""
        for label, canonical in KNOWN_KEYS.items():
            if content.startswith(label) or content.startswith(label + " "):
                return canonical
            # Also match like "图 号" separated? skip for now.
        return None

    @staticmethod
    def _bbox_of_texts(texts: list) -> BoundingBox:
        xs = [t.position[0] for t in texts]
        ys = [t.position[1] for t in texts]
        if not xs:
            return BoundingBox()
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        return BoundingBox(
            min_x=min_x,
            min_y=min_y,
            max_x=max_x,
            max_y=max_y,
            width=max_x - min_x,
            height=max_y - min_y,
        )

    @staticmethod
    def _dominant_layer(texts: list) -> str:
        from collections import Counter

        layers = Counter(t.layer for t in texts if t.layer)
        return layers.most_common(1)[0][0] if layers else ""


def extract_title_block(
    texts: list,
    frame_bbox: BoundingBox | None = None,
    entities: list | None = None,
) -> TitleBlock | None:
    """Convenience wrapper for TitleBlockExtractor.analyze()."""
    return TitleBlockExtractor().analyze(texts, frame_bbox, entities)
