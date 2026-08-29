"""Semantic analysis — 图框/标题栏/设备/管道识别.

Everything here is rule-based inference (DataTier.AI_INFERENCE /
"rule_based"). Every result carries a confidence value. If something
cannot be determined, the field is left empty — nothing is guessed.
"""

from src.semantic.analyzer import SemanticAnalyzer, analyze
from src.semantic.equipment_extractor import EquipmentExtractor
from src.semantic.frame_detector import FrameDetector
from src.semantic.pipe_extractor import PipeExtractor
from src.semantic.title_block import TitleBlockExtractor

__all__ = [
    "SemanticAnalyzer",
    "analyze",
    "EquipmentExtractor",
    "FrameDetector",
    "PipeExtractor",
    "TitleBlockExtractor",
]
