"""SQLAlchemy ORM models for CAD Knowledge Base database."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Column, String, Integer, Float, Text, Boolean,
    DateTime, ForeignKey, Index, UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""
    pass


class DrawingModel(Base):
    """Drawings table — stores top-level drawing metadata."""
    __tablename__ = "drawings"

    drawing_id = Column(String, primary_key=True)
    file_name = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_hash = Column(String, nullable=False, unique=True)
    file_size = Column(Integer, nullable=False)
    file_type = Column(String, nullable=False)
    cad_version = Column(String)
    cad_version_name = Column(String)
    units = Column(String)
    insunits = Column(Integer)
    created_time = Column(DateTime)
    modified_time = Column(DateTime)
    parser = Column(String)
    parser_version = Column(String)
    parse_status = Column(String, nullable=False)
    parse_time = Column(DateTime)
    entity_count = Column(Integer, default=0)
    text_count = Column(Integer, default=0)
    dimension_count = Column(Integer, default=0)
    layer_count = Column(Integer, default=0)
    block_count = Column(Integer, default=0)
    layout_count = Column(Integer, default=0)
    data_completeness = Column(Float, default=0.0)
    thumbnail_path = Column(String)
    raw_data_path = Column(String)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    # Relationships
    layers = relationship("LayerModel", back_populates="drawing", cascade="all, delete-orphan")
    entities = relationship("EntityModel", back_populates="drawing", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_drawings_file_name", "file_name"),
        Index("idx_drawings_file_type", "file_type"),
        Index("idx_drawings_parse_status", "parse_status"),
    )


class LayerModel(Base):
    """Layers table."""
    __tablename__ = "layers"

    layer_id = Column(String, primary_key=True)
    drawing_id = Column(String, ForeignKey("drawings.drawing_id"), nullable=False)
    name = Column(String, nullable=False)
    color = Column(Integer, default=7)
    linetype = Column(String, default="Continuous")
    lineweight = Column(Integer, default=-2)
    is_on = Column(Boolean, default=True)
    is_frozen = Column(Boolean, default=False)
    is_locked = Column(Boolean, default=False)
    entity_count = Column(Integer, default=0)

    drawing = relationship("DrawingModel", back_populates="layers")

    __table_args__ = (
        UniqueConstraint("drawing_id", "name", name="uq_layers_drawing_name"),
    )


class BlockDefModel(Base):
    """Block definitions table."""
    __tablename__ = "block_definitions"

    block_id = Column(String, primary_key=True)
    drawing_id = Column(String, ForeignKey("drawings.drawing_id"), nullable=False)
    name = Column(String, nullable=False)
    base_point = Column(Text)  # JSON
    is_anonymous = Column(Boolean, default=False)
    is_layout = Column(Boolean, default=False)
    entity_count = Column(Integer, default=0)
    has_attributes = Column(Boolean, default=False)
    source_file = Column(String)

    __table_args__ = (
        UniqueConstraint("drawing_id", "name", name="uq_blocks_drawing_name"),
    )


class LayoutModel(Base):
    """Layouts table."""
    __tablename__ = "layouts"

    layout_id = Column(String, primary_key=True)
    drawing_id = Column(String, ForeignKey("drawings.drawing_id"), nullable=False)
    name = Column(String, nullable=False)
    layout_type = Column(String, default="model")
    tab_order = Column(Integer, default=0)
    viewport_count = Column(Integer, default=0)
    entity_count = Column(Integer, default=0)
    plot_settings = Column(Text)  # JSON


class EntityModel(Base):
    """Entities table — the core table storing all CAD entities."""
    __tablename__ = "entities"

    entity_id = Column(String, primary_key=True)
    drawing_id = Column(String, ForeignKey("drawings.drawing_id"), nullable=False)
    handle = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    layer = Column(String, default="0")
    layout = Column(String, default="Model")
    space = Column(String, default="model")
    block_name = Column(String)
    color = Column(Integer, default=256)
    linetype = Column(String, default="BYLAYER")
    lineweight = Column(Integer, default=-2)
    bbox_min_x = Column(Float)
    bbox_min_y = Column(Float)
    bbox_min_z = Column(Float)
    bbox_max_x = Column(Float)
    bbox_max_y = Column(Float)
    bbox_max_z = Column(Float)
    coordinates = Column(Text)  # JSON
    properties = Column(Text)  # JSON
    source_file = Column(String)
    source_handle = Column(String)
    source_layer = Column(String)
    data_tier = Column(String, default="normalized")
    created_at = Column(DateTime, default=datetime.now)

    drawing = relationship("DrawingModel", back_populates="entities")

    __table_args__ = (
        Index("idx_entities_drawing", "drawing_id"),
        Index("idx_entities_type", "entity_type"),
        Index("idx_entities_layer", "layer"),
        Index("idx_entities_handle", "handle"),
        Index("idx_entities_bbox", "bbox_min_x", "bbox_min_y", "bbox_max_x", "bbox_max_y"),
    )


class TextModel(Base):
    """Texts table — extracted text for full-text search."""
    __tablename__ = "texts"

    text_id = Column(String, primary_key=True)
    entity_id = Column(String, ForeignKey("entities.entity_id"), nullable=False)
    drawing_id = Column(String, ForeignKey("drawings.drawing_id"), nullable=False)
    text_content = Column(Text, nullable=False)
    raw_text = Column(Text)
    position = Column(Text)  # JSON
    rotation = Column(Float, default=0)
    height = Column(Float, default=0)
    text_type = Column(String, default="TEXT")
    style = Column(String)
    width_factor = Column(Float, default=1.0)
    layer = Column(String, default="0")
    layout = Column(String, default="Model")
    block_name = Column(String)
    handle = Column(String)

    __table_args__ = (
        Index("idx_texts_drawing", "drawing_id"),
        Index("idx_texts_layer", "layer"),
        Index("idx_texts_type", "text_type"),
    )


class DimensionModel(Base):
    """Dimensions table — extracted dimensions."""
    __tablename__ = "dimensions"

    dimension_id = Column(String, primary_key=True)
    entity_id = Column(String, ForeignKey("entities.entity_id"), nullable=False)
    drawing_id = Column(String, ForeignKey("drawings.drawing_id"), nullable=False)
    dimension_type = Column(String)
    measurement = Column(Float)
    text_content = Column(Text)
    defpoint1 = Column(Text)  # JSON
    defpoint2 = Column(Text)  # JSON
    defpoint3 = Column(Text)  # JSON
    dimline_point = Column(Text)  # JSON
    style = Column(String)
    rotation = Column(Float, default=0)
    layer = Column(String, default="0")
    layout = Column(String, default="Model")
    handle = Column(String)

    __table_args__ = (
        Index("idx_dims_drawing", "drawing_id"),
        Index("idx_dims_type", "dimension_type"),
    )


class BlockAttributeModel(Base):
    """Block attributes table."""
    __tablename__ = "block_attributes"

    attrib_id = Column(String, primary_key=True)
    drawing_id = Column(String, ForeignKey("drawings.drawing_id"), nullable=False)
    insert_entity_id = Column(String, ForeignKey("entities.entity_id"))
    block_name = Column(String, nullable=False)
    tag = Column(String, nullable=False)
    value = Column(Text)
    position = Column(Text)  # JSON
    height = Column(Float, default=0)
    rotation = Column(Float, default=0)
    layer = Column(String, default="0")
    insert_position = Column(Text)  # JSON
    handle = Column(String)

    __table_args__ = (
        Index("idx_attribs_drawing", "drawing_id"),
        Index("idx_attribs_block", "block_name"),
    )


class ParseLogModel(Base):
    """Parse logs table — stores parse operation logs."""
    __tablename__ = "parse_logs"

    log_id = Column(String, primary_key=True)
    drawing_id = Column(String, ForeignKey("drawings.drawing_id"))
    timestamp = Column(DateTime, nullable=False, default=datetime.now)
    level = Column(String, nullable=False)
    operation = Column(String)
    message = Column(Text)
    details = Column(Text)  # JSON


class DrawingRevisionModel(Base):
    """Drawing revision history table."""
    __tablename__ = "drawing_revisions"

    revision_id = Column(String, primary_key=True)
    drawing_id = Column(String, ForeignKey("drawings.drawing_id"), nullable=False)
    revision_number = Column(String)
    revision_label = Column(String)
    file_hash = Column(String, nullable=False)
    file_size = Column(Integer)
    modified_time = Column(DateTime)
    changes_summary = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


# ─── Semantic Analysis Tables (Phase 3) ─────────────────────────────

class DrawingFrameModel(Base):
    """Drawing frames table — recognized 图框."""
    __tablename__ = "drawing_frames"

    frame_id = Column(String, primary_key=True)
    drawing_id = Column(String, ForeignKey("drawings.drawing_id"), nullable=False)
    min_x = Column(Float, default=0.0)
    min_y = Column(Float, default=0.0)
    max_x = Column(Float, default=0.0)
    max_y = Column(Float, default=0.0)
    width = Column(Float, default=0.0)
    height = Column(Float, default=0.0)
    layer = Column(String)
    handle = Column(String)
    entity_count = Column(Integer, default=0)
    source = Column(String, default="rule_based")
    confidence = Column(Float, default=1.0)


class TitleBlockModel(Base):
    """Title blocks table — recognized 标题栏."""
    __tablename__ = "title_blocks"

    title_block_id = Column(String, primary_key=True)
    drawing_id = Column(String, ForeignKey("drawings.drawing_id"), nullable=False)
    min_x = Column(Float, default=0.0)
    min_y = Column(Float, default=0.0)
    max_x = Column(Float, default=0.0)
    max_y = Column(Float, default=0.0)
    width = Column(Float, default=0.0)
    height = Column(Float, default=0.0)
    layer = Column(String)
    confidence = Column(Float, default=0.0)
    source = Column(String, default="rule_based")


class TitleBlockFieldModel(Base):
    """Title block fields table — key-value pairs from 标题栏."""
    __tablename__ = "title_block_fields"

    field_id = Column(String, primary_key=True)
    drawing_id = Column(String, ForeignKey("drawings.drawing_id"), nullable=False)
    title_block_id = Column(String, ForeignKey("title_blocks.title_block_id"))
    key = Column(String)
    value = Column(Text)
    raw_key = Column(Text)
    layer = Column(String)
    handle = Column(String)
    x = Column(Float, default=0.0)
    y = Column(Float, default=0.0)
    confidence = Column(Float, default=0.0)
    source = Column(String, default="rule_based")


class EquipmentModel(Base):
    """Equipment table — recognized 设备."""
    __tablename__ = "equipment"

    equipment_id = Column(String, primary_key=True)
    drawing_id = Column(String, ForeignKey("drawings.drawing_id"), nullable=False)
    equipment_no = Column(String)
    equipment_name = Column(String)
    block_name = Column(String)
    layer = Column(String)
    handle = Column(String)
    x = Column(Float, default=0.0)
    y = Column(Float, default=0.0)
    attributes = Column(Text)  # JSON
    confidence = Column(Float, default=0.0)
    source = Column(String, default="rule_based")


class PipeModel(Base):
    """Pipes table — recognized 管道."""
    __tablename__ = "pipes"

    pipe_id = Column(String, primary_key=True)
    drawing_id = Column(String, ForeignKey("drawings.drawing_id"), nullable=False)
    pipe_no = Column(String)
    diameter = Column(String)
    material = Column(String)
    layer = Column(String)
    handle = Column(String)
    x = Column(Float, default=0.0)
    y = Column(Float, default=0.0)
    confidence = Column(Float, default=0.0)
    source = Column(String, default="rule_based")


class SpatialRelationshipModel(Base):
    """Spatial relationships table — 实体空间关系 (Phase 4)."""
    __tablename__ = "spatial_relationships"

    rel_id = Column(String, primary_key=True)
    drawing_id = Column(String, ForeignKey("drawings.drawing_id"), nullable=False)
    entity_a_id = Column(String, nullable=False)
    entity_b_id = Column(String, nullable=False)
    entity_a_type = Column(String)
    entity_b_type = Column(String)
    relationship_type = Column(String, nullable=False)
    distance = Column(Float)
    confidence = Column(Float, default=1.0)
    source = Column(String, default="computed")
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_spatial_drawing", "drawing_id"),
        Index("idx_spatial_type", "relationship_type"),
    )


# ─── Unified File Registry Tables (Phase 2) ──────────────────────────
# 多格式统一文件登记：files / file_sources / projects / file_relations / file_versions
# 原则：原始文件不移动；资料库保存副本；路径解耦；Hash 去重；版本可追溯。

class FileModel(Base):
    """统一文件表（全格式通用，CAD 文件通过 drawing_id 关联 drawings）。"""
    __tablename__ = "files"

    file_id = Column(String, primary_key=True)          # UUID
    sha256 = Column(String, nullable=False)
    original_name = Column(String, nullable=False)
    original_path = Column(String, nullable=False)      # 原始路径（仅引用）
    archive_path = Column(String)                       # 副本路径（OriginalFiles 内）
    file_type = Column(String, nullable=False)          # FileType.value
    source_type = Column(String)                        # cad/word/excel/pdf/project/image/other
    file_size = Column(Integer, default=0)
    created_time = Column(DateTime)
    modified_time = Column(DateTime)
    import_time = Column(DateTime, default=datetime.now)
    project_id = Column(String)                         # FK projects.project_id
    category = Column(String)
    tags = Column(Text)                                 # JSON list
    parser = Column(String)
    parse_status = Column(String, default="pending")
    parse_time = Column(DateTime)
    drawing_id = Column(String)                         # CAD 关联
    extra = Column(Text)                                # JSON

    __table_args__ = (
        Index("idx_files_sha256", "sha256"),
        Index("idx_files_name", "original_name"),
        Index("idx_files_type", "file_type"),
        Index("idx_files_source_type", "source_type"),
        Index("idx_files_project", "project_id"),
        Index("idx_files_status", "parse_status"),
    )


class FileSourceModel(Base):
    """文件来源表：同一 SHA256 可对应多个原始路径。"""
    __tablename__ = "file_sources"

    source_id = Column(String, primary_key=True)
    file_id = Column(String, nullable=False)            # FK files.file_id
    original_path = Column(String, nullable=False)
    found_time = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_sources_file", "file_id"),
        Index("idx_sources_path", "original_path"),
    )


class ProjectModel(Base):
    """项目表：项目名称 + 推断置信度 + 来源。"""
    __tablename__ = "projects"

    project_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    confidence = Column(Float, default=0.0)
    source = Column(String)                             # filename/title_block/word_title/user/...
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_projects_name", "name"),
    )


class FileRelationModel(Base):
    """文件关联表：同项目/同设备/同材料等。"""
    __tablename__ = "file_relations"

    rel_id = Column(String, primary_key=True)
    file_a = Column(String, nullable=False)
    file_b = Column(String, nullable=False)
    relation_type = Column(String, nullable=False)      # same_project/same_equipment/...
    confidence = Column(Float, default=0.0)
    source = Column(String, default="computed")
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_rels_a", "file_a"),
        Index("idx_rels_b", "file_b"),
        Index("idx_rels_type", "relation_type"),
    )


class FileVersionModel(Base):
    """文件版本表：SHA256 变化即新版本，保留历史副本与解析。"""
    __tablename__ = "file_versions"

    version_id = Column(String, primary_key=True)
    file_id = Column(String, nullable=False)
    version_no = Column(Integer, default=1)
    sha256 = Column(String, nullable=False)
    archive_path = Column(String)
    file_size = Column(Integer, default=0)
    modified_time = Column(DateTime)
    parse_status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_versions_file", "file_id"),
        Index("idx_versions_sha", "sha256"),
    )


class DocumentContentModel(Base):
    """文档内容表（Phase 5）：非 CAD 文件的解析内容，供统一全文搜索。"""
    __tablename__ = "document_contents"

    file_id = Column(String, primary_key=True)   # FK files.file_id
    source_type = Column(String)                 # word/excel/pdf/...
    title = Column(String)
    content = Column(Text)                       # 纯文本（全文搜索用）
    markdown = Column(Text)                      # LLM 友好版本
    json_path = Column(String)                   # ParsedData JSON
    md_path = Column(String)
    txt_path = Column(String)
    source = Column(String, default="text")      # text | ocr
    confidence = Column(Float, default=1.0)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("idx_doc_content_type", "source_type"),
        Index("idx_doc_content_title", "title"),
    )


class EngineeringEntityModel(Base):
    """工程实体候选登记表（阶段1：只登记，不建关系）。

    从资料中提取的"候选工程实体"（设备/基础/管道/阀门/仪表/材料...）。
    原则：发现实体 ≠ 确认实体 ≠ 建立关系。
    每个实体记录来源证据：来源文件/页码/位置/原始文字/图号/版本/提取方式/置信度。
    """
    __tablename__ = "engineering_entities"

    entity_id = Column(String, primary_key=True)      # UUID
    entity_type = Column(String, nullable=False)      # equipment/foundation/pipeline/valve/instrument/material/...
    entity_no = Column(String)                        # 候选编号，如 K-205 / FC0203DC01
    entity_name = Column(String)                      # 候选名称
    # 来源证据（总纲十）
    source_file_id = Column(String)                   # FK files.file_id
    source_drawing_id = Column(String)                # FK drawings.drawing_id（CAD 来源）
    source_page = Column(String)                      # 页码/图纸位置
    source_position = Column(Text)                    # 坐标/位置（JSON）
    raw_text = Column(Text)                           # 原始文字
    drawing_no = Column(String)                       # 图号
    file_version = Column(Integer, default=1)         # 文件版本
    extraction_method = Column(String)                # equipment_table/dwg_text/doc_regex/...
    confidence = Column(Float, default=0.0)           # 提取置信度
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_entities_cand_type", "entity_type"),
        Index("idx_entities_cand_no", "entity_no"),
        Index("idx_entities_cand_file", "source_file_id"),
    )


class EquipmentTagModel(Base):
    """设备位号标注表（texts 正则抽取，2.5D 空间语义图的锚点数据）。

    数据探查结论：Manono 图纸的设备位号主要以 TEXT 标注形式存在
    （texts 表整串匹配 1 万余条，覆盖 130+ 张工艺图），远多于
    equipment 表 ATTRIB 通道（仅电气类图纸有效）。位号格式：
    - 设备位号: FC0203ME01（2字母+4数字子系统号+2字母+2数字+可选后缀）
    - 管道编号: P01-PP-01AC1（P+2数字-2字母-2数字+后缀）
    位号内含子系统编号（如 0203），与 file_relations 子系统聚类一致。
    """
    __tablename__ = "equipment_tags"

    tag_id = Column(String, primary_key=True)      # UUID
    drawing_id = Column(String, nullable=False)    # FK drawings.drawing_id
    tag_no = Column(String, nullable=False)        # 位号，如 FC0203ME01 / P01-PP-01
    tag_type = Column(String, default="equipment") # equipment / pipeline
    x = Column(Float)                              # 标注点坐标（图纸单位）
    y = Column(Float)
    height = Column(Float)                         # 文字高度（用于热区尺寸估算）
    layer = Column(String)
    text_id = Column(String)                       # FK texts.text_id（溯源）
    subsystem_no = Column(String)                  # 位号内子系统编号，如 0203
    source = Column(String, default="text_regex")
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_equiptags_drawing", "drawing_id"),
        Index("idx_equiptags_no", "tag_no"),
        Index("idx_equiptags_subsys", "subsystem_no"),
    )


class DeviceMasterModel(Base):
    """设备主数据表（跨图对齐后的统一设备视图）。

    由 equipment_tags 按 tag_no 聚合生成，去重并归一化。
    关键字段：
    - tag_no: 原始位号（如 FC0203ME01）
    - normalized_tag: 标准化位号（大写、去空格、统一连字符）
    - category: 从位号前缀推断的设备大类（ME=电机/机械设备，DC=配电柜，
      HX=换热器，TK=储罐，PM=泵，FC=风机，CF=压缩机/风机，...）
    - subsystem_no: 主属子系统（取出现频次最高的值）
    - name: 最常见的设备名称（来自 equip_name / text_content）
    - drawing_count: 该设备在多少张图出现
    - occurrence_count: 总标注点数
    - bbox_min/max_x/y: 各图坐标极值（仅参考，因不同图坐标系不同）
    """
    __tablename__ = "device_master"

    device_id = Column(String, primary_key=True)      # UUID
    tag_no = Column(String, nullable=False, unique=True)
    normalized_tag = Column(String, nullable=False)
    category = Column(String)
    subsystem_no = Column(String)
    name = Column(String)
    drawing_count = Column(Integer, default=0)
    occurrence_count = Column(Integer, default=0)
    bbox_min_x = Column(Float)
    bbox_min_y = Column(Float)
    bbox_max_x = Column(Float)
    bbox_max_y = Column(Float)
    confidence = Column(Float, default=0.0)
    source = Column(Text)                            # 生成来源说明
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("idx_device_master_tag", "tag_no"),
        Index("idx_device_master_norm", "normalized_tag"),
        Index("idx_device_master_subsys", "subsystem_no"),
        Index("idx_device_master_category", "category"),
    )


class DeviceOccurrenceModel(Base):
    """设备出现记录表：某设备在某张图纸中的具体位置。

    因不同图纸坐标系不同，设备主记录无法给出全局统一坐标。
    本表按 (device_id, drawing_id) 保留每次出现，供 2.5D 视图按当前图纸映射。
    """
    __tablename__ = "device_occurrences"

    occurrence_id = Column(String, primary_key=True)  # UUID
    device_id = Column(String, nullable=False)        # FK device_master.device_id
    drawing_id = Column(String, nullable=False)        # FK drawings.drawing_id
    file_id = Column(String)                            # FK files.file_id
    tag_no = Column(String, nullable=False)
    x = Column(Float)
    y = Column(Float)
    z = Column(Float)
    text_content = Column(Text)                         # 原始标注文字
    layer = Column(String)
    source = Column(String, default="equipment_tags")
    confidence = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_devocc_device", "device_id"),
        Index("idx_devocc_drawing", "drawing_id"),
        Index("idx_devocc_tag", "tag_no"),
    )
