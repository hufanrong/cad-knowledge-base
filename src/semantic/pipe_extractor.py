"""Pipe information extraction (管道信息识别).

Pipe data in CAD drawings appears mostly as:
- Text annotations near pipes, e.g. "DN100", "φ4500×45000", "Q235A"
- Pipe line numbers like "PL-101" or "管线号 01-PL-1001-001"
- Layer names containing 管道/PIPE/DN

Strategy (rule-based, conservative):
   1. Scan TEXT/MTEXT for pipe-related patterns:
      - Diameter: DN100 / φ4500 / Φ600 / D200
      - Material keywords: Q235, 20#, 304, 316L, 16Mn, etc.
      - Pipe line numbers: PL-101 / PG-1001 / 管线号 01-PL-1001-001
2. Scan layer names for pipe hints (管道, PIPE, DN).
3. Build PipeInfo with the found fields; never guess missing values.
"""

from __future__ import annotations

import re

from src.normalizer.schema import PipeInfo
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.semantic.pipe")

# Diameter patterns
DN_RE = re.compile(r"DN\s*\d+", re.IGNORECASE)
PHI_RE = re.compile(r"[φΦ]\s*\d+(?:\.\d+)?")
PIPE_LINE_RE = re.compile(r"(?:PL|PG|PIPELINE|管线号)\s*[-:]?\s*[\w\-]+", re.IGNORECASE)

# Material patterns — require a boundary so "45" doesn't match inside
# "φ4500" and "20" doesn't match inside "2000".
MATERIAL_RE = re.compile(
    r"(?<![φΦ\d×x])"
    r"(?:Q235[AB]?|Q345[AB]?|16Mn|304L?|316L?|304|316|A3|40Cr|35CrMo|20G|15CrMo|12Cr1MoV|45#|20#)"
    r"(?!\d)",
    re.IGNORECASE,
)

# Layer name hints for pipe layers
PIPE_LAYER_KEYWORDS = ["管道", "管线", "PIPE", "DN", "管路"]


class PipeExtractor:
    """Extract pipe information from parsed texts and layers."""

    def analyze(
        self,
        texts: list,
        layers: list | None = None,
    ) -> list[PipeInfo]:
        """Extract pipe info.

        Args:
            texts: List of TextEntity.
            layers: Optional list of Layer (for layer-name hints).

        Returns:
            List of PipeInfo.
        """
        pipes: list[PipeInfo] = []
        seen: set[tuple] = set()

        for t in texts:
            content = (t.text_content or "").strip()
            if not content:
                continue

            diameter = self._find_diameter(content)
            material = self._find_material(content)
            pipe_no = self._find_pipe_no(content)

            if not (diameter or material or pipe_no):
                continue

            key = (content, t.handle)
            if key in seen:
                continue
            seen.add(key)

            confidence = 0.0
            signals = sum(1 for v in (diameter, material, pipe_no) if v)
            if signals >= 2:
                confidence = 0.85
            elif diameter or pipe_no:
                confidence = 0.65
            else:
                confidence = 0.5

            pipes.append(PipeInfo(
                pipe_no=pipe_no or "",
                diameter=diameter or "",
                material=material or "",
                layer=t.layer,
                handle=t.handle,
                x=t.position[0],
                y=t.position[1],
                confidence=round(confidence, 2),
                source="rule_based",
            ))

        # Layer-name based pipes (low confidence, only if no text matches)
        if layers and not pipes:
            for layer in layers:
                name = (layer.name or "").strip()
                if not name:
                    continue
                if any(kw.lower() in name.lower() for kw in PIPE_LAYER_KEYWORDS):
                    pipes.append(PipeInfo(
                        layer=name,
                        confidence=0.4,
                        source="rule_based",
                    ))

        logger.info(f"管道识别: 找到 {len(pipes)} 条管道信息")
        return pipes

    # ── helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _find_diameter(content: str) -> str:
        m = DN_RE.search(content)
        if m:
            return m.group(0).upper().replace(" ", "")
        m = PHI_RE.search(content)
        if m:
            return m.group(0)
        return ""

    @staticmethod
    def _find_material(content: str) -> str:
        m = MATERIAL_RE.search(content)
        return m.group(0) if m else ""

    @staticmethod
    def _find_pipe_no(content: str) -> str:
        m = PIPE_LINE_RE.search(content)
        return m.group(0) if m else ""


def extract_pipes(texts: list, layers: list | None = None) -> list[PipeInfo]:
    """Convenience wrapper for PipeExtractor.analyze()."""
    return PipeExtractor().analyze(texts, layers)
