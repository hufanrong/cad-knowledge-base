"""Semantic analyzer orchestration.

Runs the full semantic analysis pipeline on a ParseResult:
1. Frame detection (图框)
2. Title block extraction (标题栏)
3. Equipment extraction (设备)
4. Pipe extraction (管道)

All outputs are rule-based (AI_INFERENCE tier) with confidence values.
The analyzer never fabricates values.
"""

from __future__ import annotations

from src.normalizer.schema import ParseResult
from src.semantic.equipment_extractor import EquipmentExtractor
from src.semantic.frame_detector import FrameDetector
from src.semantic.pipe_extractor import PipeExtractor
from src.semantic.title_block import TitleBlockExtractor
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.semantic.analyzer")


class SemanticAnalyzer:
    """Orchestrates semantic analysis on a parsed drawing."""

    def __init__(self) -> None:
        self.frame_detector = FrameDetector()
        self.title_block_extractor = TitleBlockExtractor()
        self.equipment_extractor = EquipmentExtractor()
        self.pipe_extractor = PipeExtractor()

    def analyze(self, result: ParseResult) -> ParseResult:
        """Run all semantic analyses, mutating and returning the result."""
        if result.drawing.parse_status != "success":
            logger.info("语义分析: 解析未成功，跳过")
            return result

        drawing_id = result.drawing.drawing_id
        logger.info(f"开始语义分析: {result.drawing.file_name}")

        # 1. Frame detection
        frame = self.frame_detector.analyze(result.entities)
        if frame:
            frame.drawing_id = drawing_id
            result.frames.append(frame)

        # 2. Title block (needs frame region)
        tb = self.title_block_extractor.analyze(
            texts=result.texts,
            frame_bbox=frame.bounding_box if frame else None,
            entities=result.entities,
        )
        if tb:
            tb.drawing_id = drawing_id
            for f in tb.fields:
                f.drawing_id = drawing_id
            result.title_blocks.append(tb)

        # 3. Equipment extraction
        for eq in self.equipment_extractor.analyze(
            attributes=result.attributes,
            entities=result.entities,
            texts=result.texts,
        ):
            eq.drawing_id = drawing_id
            result.equipment.append(eq)

        # 4. Pipe extraction
        for p in self.pipe_extractor.analyze(
            texts=result.texts,
            layers=result.layers,
        ):
            p.drawing_id = drawing_id
            result.pipes.append(p)

        logger.info(
            f"语义分析完成: 图框={len(result.frames)}, 标题栏={len(result.title_blocks)}, "
            f"设备={len(result.equipment)}, 管道={len(result.pipes)}"
        )
        return result


def analyze(result: ParseResult) -> ParseResult:
    """Convenience wrapper for SemanticAnalyzer().analyze()."""
    return SemanticAnalyzer().analyze(result)
