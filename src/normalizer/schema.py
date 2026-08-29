"""Unified CAD Data Schema (Pydantic models).

This module defines the standard data model that all CAD parsers
(DXF, DWG, PDF) must convert their output to.

Key principle: Every piece of data must be tagged with its source
(data_tier) and provenance (source_location).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─── Enums ───────────────────────────────────────────────────────────

class FileType(str, Enum):
    """Unified file type (Phase 2 expansion: multi-format support)."""
    # CAD
    DWG = "dwg"
    DXF = "dxf"
    DWT = "dwt"
    DWS = "dws"
    # Documents
    DOCX = "docx"
    DOC = "doc"
    PDF = "pdf"
    RTF = "rtf"
    TXT = "txt"
    # Spreadsheets
    XLSX = "xlsx"
    XLS = "xls"
    XLSM = "xlsm"
    CSV = "csv"
    # Presentations
    PPTX = "pptx"
    PPT = "ppt"
    # Structured data
    XML = "xml"
    JSON = "json"
    HTML = "html"
    # Project
    MPP = "mpp"
    # Media
    IMAGE = "image"
    # Other
    UNKNOWN = "unknown"


class SourceType(str, Enum):
    """High-level source category (Phase 2)."""
    CAD = "cad"
    WORD = "word"
    EXCEL = "excel"
    PDF = "pdf"
    PROJECT = "project"
    IMAGE = "image"
    OTHER = "other"


class ParseStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    PENDING = "pending"


class DataTier(str, Enum):
    """Data classification tier.
    
    RAW: Directly from CAD file, unmodified.
    NORMALIZED: Converted to unified schema, values unchanged.
    DERIVED: Computed from raw data (e.g., arc length from radius+angles).
    AI_INFERENCE: AI identified or inferred, may have uncertainty.
    USER_NOTE: Manually added by user.
    """
    RAW = "raw"
    NORMALIZED = "normalized"
    DERIVED = "derived"
    AI_INFERENCE = "ai_inference"
    USER_NOTE = "user_note"


class SpaceType(str, Enum):
    MODEL = "model"
    PAPER = "paper"


class RelationshipType(str, Enum):
    NEAR = "near"
    INTERSECTS = "intersects"
    CONTAINS = "contains"
    BELONGS_TO = "belongs_to"
    ANNOTATES = "annotates"
    REFERENCES = "references"


# ─── DWG Version Mapping ─────────────────────────────────────────────

DWG_VERSION_MAP: dict[bytes, str] = {
    b"AC1.50": "AutoCAD R2.05",
    b"AC2.10": "AutoCAD R2.10",
    b"AC1001": "AutoCAD R2.5",
    b"AC1002": "AutoCAD R2.6",
    b"AC1003": "AutoCAD R9",
    b"AC1004": "AutoCAD R10",
    b"AC1006": "AutoCAD R11/R12",
    b"AC1009": "AutoCAD R12/R13",
    b"AC1012": "AutoCAD R13",
    b"AC1014": "AutoCAD R14",
    b"AC1015": "AutoCAD 2000",
    b"AC1018": "AutoCAD 2004",
    b"AC1021": "AutoCAD 2007",
    b"AC1024": "AutoCAD 2010",
    b"AC1027": "AutoCAD 2013",
    b"AC1032": "AutoCAD 2018",
    b"AC1042": "AutoCAD 2025",
}


# ─── Auxiliary Types ─────────────────────────────────────────────────

class BoundingBox(BaseModel):
    """Axis-aligned bounding box in 3D space."""
    min_x: float = 0.0
    min_y: float = 0.0
    min_z: float = 0.0
    max_x: float = 0.0
    max_y: float = 0.0
    max_z: float = 0.0
    width: float = 0.0   # derived: max_x - min_x
    height: float = 0.0  # derived: max_y - min_y


class SourceLocation(BaseModel):
    """Provenance information for tracing data back to its origin."""
    file: str = ""
    layout: str = ""
    handle: str = ""
    layer: str = ""
    coordinates: str = ""  # Human-readable: "X=1000.00 Y=2000.00"

    def to_dict(self) -> dict[str, str]:
        return self.model_dump()


class ConfidenceInfo(BaseModel):
    """Confidence metadata for AI-inferred data."""
    confidence: float = 1.0  # 0.0 to 1.0
    source: str = "raw"  # "raw" | "computed" | "rule_based" | "ai"
    status: str = "confirmed"  # "confirmed" | "uncertain" | "inferred"


# ─── Drawing Level ───────────────────────────────────────────────────

class Drawing(BaseModel):
    """Top-level drawing metadata."""
    drawing_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    file_name: str = ""
    file_path: str = ""
    file_hash: str = ""  # SHA256
    file_size: int = 0  # bytes
    file_type: FileType = FileType.UNKNOWN
    cad_version: str = ""  # e.g., "AC1032"
    cad_version_name: str = ""  # e.g., "AutoCAD 2018"
    units: str = "unknown"  # "mm" | "cm" | "m" | "inch" | "feet"
    insunits: int | None = None
    created_time: datetime | None = None
    modified_time: datetime | None = None
    parser: str = ""  # "ezdxf" | "oda+ezdxf" | "autocad_com"
    parser_version: str = ""
    parse_status: ParseStatus = ParseStatus.PENDING
    parse_time: datetime | None = None
    entity_count: int = 0
    text_count: int = 0
    dimension_count: int = 0
    layer_count: int = 0
    block_count: int = 0
    layout_count: int = 0
    data_completeness: float = 0.0  # 0.0 to 1.0
    thumbnail_path: str | None = None
    raw_data_path: str | None = None
    notes: str = ""


class Layer(BaseModel):
    """CAD layer definition."""
    layer_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    drawing_id: str = ""
    name: str = ""
    color: int = 7
    linetype: str = "Continuous"
    lineweight: int = -2  # -2 = BYLAYER
    is_on: bool = True
    is_frozen: bool = False
    is_locked: bool = False
    plot_style: str | None = None
    entity_count: int = 0


class BlockDefinition(BaseModel):
    """CAD block definition."""
    block_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    drawing_id: str = ""
    name: str = ""
    base_point: tuple[float, float, float] = (0.0, 0.0, 0.0)
    is_anonymous: bool = False
    is_layout: bool = False
    entity_count: int = 0
    has_attributes: bool = False
    source_file: str = ""


class LayoutInfo(BaseModel):
    """CAD layout (Model Space or Paper Space)."""
    layout_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    drawing_id: str = ""
    name: str = ""
    layout_type: str = "model"  # "model" | "paper"
    tab_order: int = 0
    viewport_count: int = 0
    entity_count: int = 0
    plot_settings: dict[str, Any] = Field(default_factory=dict)


class ViewportInfo(BaseModel):
    """Paper space viewport."""
    viewport_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    drawing_id: str = ""
    layout_name: str = ""
    view_center: tuple[float, float] = (0.0, 0.0)
    view_height: float = 0.0
    view_width: float = 0.0
    scale: float = 1.0
    target_point: tuple[float, float, float] = (0.0, 0.0, 0.0)
    direction: tuple[float, float, float] = (0.0, 0.0, 1.0)


# ─── Entity Level ────────────────────────────────────────────────────

class CADEntity(BaseModel):
    """Unified CAD entity — base for all entity types.
    
    The `properties` dict holds type-specific data.
    See entity property models below.
    """
    entity_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    drawing_id: str = ""
    handle: str = ""
    entity_type: str = ""  # "LINE" | "CIRCLE" | "TEXT" | etc.
    layer: str = "0"
    layout: str = "Model"
    space: SpaceType = SpaceType.MODEL
    block_name: str | None = None
    color: int = 256  # 256 = BYLAYER
    linetype: str = "BYLAYER"
    lineweight: int = -2
    bounding_box: BoundingBox = Field(default_factory=BoundingBox)
    coordinates: list[float] = Field(default_factory=list)  # flattened [x1,y1,z1, x2,y2,z2, ...]
    properties: dict[str, Any] = Field(default_factory=dict)
    source_file: str = ""
    source_handle: str = ""
    source_layer: str = ""
    data_tier: DataTier = DataTier.NORMALIZED


# ─── Text ────────────────────────────────────────────────────────────

class TextEntity(BaseModel):
    """Extracted text entity for full-text search."""
    text_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    entity_id: str = ""
    drawing_id: str = ""
    text_content: str = ""
    raw_text: str = ""  # Original MTEXT with formatting codes
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: float = 0.0  # degrees
    height: float = 0.0
    text_type: str = "TEXT"  # "TEXT" | "MTEXT"
    style: str = ""
    width_factor: float = 1.0
    layer: str = "0"
    layout: str = "Model"
    block_name: str | None = None
    handle: str = ""


# ─── Dimension ───────────────────────────────────────────────────────

class DimensionEntity(BaseModel):
    """Extracted dimension entity."""
    dimension_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    entity_id: str = ""
    drawing_id: str = ""
    dimension_type: str = ""  # "linear" | "aligned" | "angular" | "radius" | "diameter" | "ordinate"
    measurement: float = 0.0  # Actual measured value from CAD
    text_content: str = ""  # Display text
    defpoint1: tuple[float, float, float] = (0.0, 0.0, 0.0)
    defpoint2: tuple[float, float, float] = (0.0, 0.0, 0.0)
    defpoint3: tuple[float, float, float] = (0.0, 0.0, 0.0)
    dimline_point: tuple[float, float, float] = (0.0, 0.0, 0.0)
    style: str = ""
    rotation: float = 0.0
    layer: str = "0"
    layout: str = "Model"
    handle: str = ""


# ─── Block Attribute ─────────────────────────────────────────────────

class BlockAttribute(BaseModel):
    """Block insert attribute (tag-value pair)."""
    attrib_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    drawing_id: str = ""
    insert_entity_id: str = ""
    block_name: str = ""
    tag: str = ""
    value: str = ""
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    height: float = 0.0
    rotation: float = 0.0
    layer: str = "0"
    insert_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    handle: str = ""


# ─── Spatial Relationship ────────────────────────────────────────────

class SpatialRelationship(BaseModel):
    """Relationship between two entities in space."""
    rel_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    drawing_id: str = ""
    entity_a_id: str = ""
    entity_b_id: str = ""
    relationship_type: RelationshipType = RelationshipType.NEAR
    distance: float | None = None
    confidence: float = 1.0
    source: str = "computed"  # "computed" | "rule_based"


# ─── Semantic Analysis Models ────────────────────────────────────────
# These describe high-level meaning extracted from a drawing.
# IMPORTANT: everything here is AI_INFERENCE / rule-based and carries a
# confidence value. If we cannot determine a value, it stays empty —
# nothing is guessed.

class DrawingFrame(BaseModel):
    """Recognized drawing frame (图框) — the outer border rectangle."""
    frame_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    drawing_id: str = ""
    bounding_box: BoundingBox = Field(default_factory=BoundingBox)
    layer: str = ""            # layer that the frame lines belong to
    handle: str = ""           # handle of the source entity (if single entity)
    entity_count: int = 0      # number of entities forming the frame
    source: str = "rule_based" # how it was detected
    confidence: float = 1.0    # 0.0-1.0


class TitleBlockField(BaseModel):
    """A single key-value pair extracted from the title block (标题栏)."""
    field_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    drawing_id: str = ""
    key: str = ""              # normalized key, e.g. "图号" / "图纸名称"
    value: str = ""            # raw value text
    raw_key: str = ""          # original text on the key side
    layer: str = ""
    handle: str = ""
    x: float = 0.0
    y: float = 0.0
    confidence: float = 0.0
    source: str = "rule_based"


class TitleBlock(BaseModel):
    """Recognized title block (标题栏) — usually lower-right area of frame."""
    title_block_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    drawing_id: str = ""
    bounding_box: BoundingBox = Field(default_factory=BoundingBox)
    layer: str = ""
    fields: list[TitleBlockField] = Field(default_factory=list)
    confidence: float = 0.0
    source: str = "rule_based"


class EquipmentInfo(BaseModel):
    """Recognized equipment (设备) from blocks/attributes/text."""
    equipment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    drawing_id: str = ""
    equipment_no: str = ""     # e.g. "P-101" / "EQUIP_NO"
    equipment_name: str = ""   # e.g. "球磨机"
    block_name: str = ""       # source INSERT block name
    layer: str = ""
    handle: str = ""
    x: float = 0.0
    y: float = 0.0
    attributes: dict[str, str] = Field(default_factory=dict)
    confidence: float = 0.0
    source: str = "rule_based"


class PipeInfo(BaseModel):
    """Recognized pipe (管道) information."""
    pipe_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    drawing_id: str = ""
    pipe_no: str = ""          # e.g. "DN100" or line number if found
    diameter: str = ""         # e.g. "DN100" / "φ4500"
    material: str = ""         # e.g. "Q235A" if mentioned
    layer: str = ""
    handle: str = ""
    x: float = 0.0
    y: float = 0.0
    confidence: float = 0.0
    source: str = "rule_based"


# ─── Parse Result ────────────────────────────────────────────────────

class ParseResult(BaseModel):
    """Complete result of parsing a CAD file."""
    drawing: Drawing = Field(default_factory=Drawing)
    layers: list[Layer] = Field(default_factory=list)
    blocks: list[BlockDefinition] = Field(default_factory=list)
    layouts: list[LayoutInfo] = Field(default_factory=list)
    viewports: list[ViewportInfo] = Field(default_factory=list)
    entities: list[CADEntity] = Field(default_factory=list)
    texts: list[TextEntity] = Field(default_factory=list)
    dimensions: list[DimensionEntity] = Field(default_factory=list)
    attributes: list[BlockAttribute] = Field(default_factory=list)
    frames: list[DrawingFrame] = Field(default_factory=list)
    title_blocks: list[TitleBlock] = Field(default_factory=list)
    equipment: list[EquipmentInfo] = Field(default_factory=list)
    pipes: list[PipeInfo] = Field(default_factory=list)
    relationships: list[SpatialRelationship] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    quality_report: QualityReport | None = None


class QualityReport(BaseModel):
    """Data quality assessment report."""
    entity_count: int = 0
    text_count: int = 0
    dimension_count: int = 0
    layer_count: int = 0
    block_count: int = 0
    layout_count: int = 0
    attribute_count: int = 0
    viewport_count: int = 0
    parse_errors: int = 0
    parse_warnings: int = 0
    coordinate_issues: int = 0
    unit_detected: bool = False
    data_completeness: float = 0.0  # 0.0 to 1.0
    checks_passed: list[str] = Field(default_factory=list)
    checks_failed: list[str] = Field(default_factory=list)

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            f"实体数: {self.entity_count}",
            f"文字数: {self.text_count}",
            f"尺寸数: {self.dimension_count}",
            f"图层数: {self.layer_count}",
            f"块定义: {self.block_count}",
            f"块属性: {self.attribute_count}",
            f"布局数: {self.layout_count}",
            f"视口数: {self.viewport_count}",
            f"解析错误: {self.parse_errors}",
            f"解析警告: {self.parse_warnings}",
            f"坐标问题: {self.coordinate_issues}",
            f"单位识别: {'是' if self.unit_detected else '否'}",
            f"数据完整度: {self.data_completeness:.1%}",
        ]
        return "\n".join(lines)


# ─── Parse Log Entry ─────────────────────────────────────────────────

class ParseLogEntry(BaseModel):
    """A single log entry for the parse log table."""
    log_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    drawing_id: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)
    level: str = "INFO"  # "INFO" | "WARNING" | "ERROR"
    operation: str = ""
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


# ─── Unified File Registry Models (Phase 2) ──────────────────────────
# 多格式统一文件登记：File / Project / Source / Version / Relation
# 原则：原始文件不移动；资料库保存副本；路径解耦；Hash 去重；版本可追溯。

class FileRecord(BaseModel):
    """统一文件记录（全格式通用）。"""
    file_id: str = Field(default_factory=lambda: str(uuid.uuid4()))  # UUID
    sha256: str = ""
    original_name: str = ""
    original_path: str = ""      # 原始文件路径（仅引用，非依赖）
    archive_path: str = ""       # 资料库副本路径（OriginalFiles 内）
    file_type: str = ""          # FileType.value
    source_type: str = ""        # SourceType.value (cad/word/excel/pdf/project/image/other)
    file_size: int = 0
    created_time: datetime | None = None
    modified_time: datetime | None = None
    import_time: datetime = Field(default_factory=datetime.now)
    project_id: str = ""
    category: str = ""           # 用户/系统分类
    tags: list[str] = Field(default_factory=list)
    parser: str = ""             # 使用的解析器
    parse_status: str = ParseStatus.PENDING.value
    parse_time: datetime | None = None
    drawing_id: str = ""         # CAD 关联（CAD 文件指向 drawings.drawing_id）
    extra: dict[str, Any] = Field(default_factory=dict)


class ProjectRecord(BaseModel):
    """项目模型：项目名称 + 推断置信度 + 来源。"""
    project_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    confidence: float = 0.0       # 0~1；自动推断必须带置信度
    source: str = ""              # 推断来源: filename/title_block/word_title/user/...
    created_at: datetime = Field(default_factory=datetime.now)


class FileSource(BaseModel):
    """文件来源记录：同一 SHA256 可对应多个原始路径。"""
    source_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    file_id: str = ""
    original_path: str = ""
    found_time: datetime = Field(default_factory=datetime.now)


class FileRelation(BaseModel):
    """文件间关联（同项目/同设备/同材料等）。"""
    rel_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    file_a: str = ""
    file_b: str = ""
    relation_type: str = ""       # same_project/same_equipment/same_material/...
    confidence: float = 0.0
    source: str = ""              # computed/user
    created_at: datetime = Field(default_factory=datetime.now)


class FileVersion(BaseModel):
    """文件版本记录：SHA256 变化即新版本，保留历史副本与解析。"""
    version_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    file_id: str = ""
    version_no: int = 1
    sha256: str = ""
    archive_path: str = ""        # 该版本副本路径
    file_size: int = 0
    modified_time: datetime | None = None
    parse_status: str = ParseStatus.PENDING.value
    created_at: datetime = Field(default_factory=datetime.now)


# ─── Multi-format Parsed Document Models (Phase 3) ───────────────────
# Word/Excel/PDF 等非 CAD 文件的统一解析产物。
# 原则：OCR 内容必须标记 source=ocr + confidence，绝不伪装成原文。

class TableData(BaseModel):
    """结构化表格数据（Excel/Word/PDF 表格通用）。"""
    sheet: str = ""                # 工作表名（Excel）或章节（Word/PDF）
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    merged_cells: list[dict] = Field(default_factory=list)  # Excel 合并单元格


class ParsedSection(BaseModel):
    """文档章节/段落。"""
    level: int = 1                 # 标题层级（0=正文）
    title: str = ""
    text: str = ""
    page: int | None = None        # PDF 页码


class ParsedImage(BaseModel):
    """文档内图片信息。"""
    index: int = 0
    caption: str = ""              # 图片说明
    page: int | None = None


class ParsedDocument(BaseModel):
    """统一多格式解析产物（Word/Excel/PDF/图片/通用文本）。"""
    file_id: str = ""
    source_file: str = ""
    source_type: str = ""          # word/excel/pdf/image/other
    parser: str = ""               # docx_parser/excel_parser/pdf_parser/...
    parse_status: str = ParseStatus.SUCCESS.value
    source: str = "text"           # text | ocr（OCR 必须标记）
    confidence: float = 1.0        # OCR 置信度（text=1.0）
    title: str = ""
    summary: str = ""
    sections: list[ParsedSection] = Field(default_factory=list)
    tables: list[TableData] = Field(default_factory=list)
    images: list[ParsedImage] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)   # 作者/时间/属性
    content: str = ""              # 纯文本（供全文搜索/向量索引）
    markdown: str = ""             # 适合大模型读取的 Markdown 版本
    json_path: str = ""            # ParsedData 落盘路径
    md_path: str = ""
    txt_path: str = ""
    errors: list[str] = Field(default_factory=list)
