"""Unified file registry — 统一文件登记 (Phase 2).

Core services for the multi-format knowledge base:

- register_file(): SHA256 dedup + archive copy + multi-source records + versioning
- get_file() / get_original_file(): access via UUID file_id
- list_files() / search_files(): unified queries across all formats
- _archive_copy(): copy original -> OriginalFiles/<SourceType>/<hash>.<ext>

Principles:
- Original files are NEVER moved/modified/deleted.
- The KB keeps its own archive copy (original_path is only a reference).
- Same SHA256 -> single physical archive copy, multiple source records.
- Changed content -> new version, old archive + parse kept.

2026-08-31 变更（老板定案）：
- 新增 CADKB_KEEP_ARCHIVE_COPY 开关，默认 0 —— **不再保留 OriginalFiles 副本**，
  仅记录理论归档路径，解析产物全部落在 cadkb.db（结构化数据 + 向量）。
- 置 1 可恢复旧行为（复制副本）。
- 影响：scripts/build_previews.py 在原件缺失时原本回退读副本，关闭后该功能失效。
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from src.database.connection import get_session
from src.database.models import (
    DrawingModel,
    FileModel,
    FileRelationModel,
    FileSourceModel,
    FileVersionModel,
    ProjectModel,
)
from src.file_manager.hasher import compute_sha256
from src.file_manager.version_detector import detect_file_type, get_file_info
from src.normalizer.schema import FileType, ParseStatus, SourceType
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.file_registry")

# 扩展名 -> SourceType
EXT_TO_SOURCE = {
    ".dwg": SourceType.CAD, ".dxf": SourceType.CAD,
    ".dwt": SourceType.CAD, ".dws": SourceType.CAD,
    ".docx": SourceType.WORD, ".doc": SourceType.WORD, ".rtf": SourceType.WORD,
    ".xlsx": SourceType.EXCEL, ".xls": SourceType.EXCEL,
    ".xlsm": SourceType.EXCEL, ".csv": SourceType.EXCEL,
    ".pdf": SourceType.PDF,
    ".mpp": SourceType.PROJECT,
    ".jpg": SourceType.IMAGE, ".jpeg": SourceType.IMAGE,
    ".png": SourceType.IMAGE, ".bmp": SourceType.IMAGE,
    ".tif": SourceType.IMAGE, ".tiff": SourceType.IMAGE,
    ".gif": SourceType.IMAGE, ".webp": SourceType.IMAGE,
}
DEFAULT_SOURCE = SourceType.OTHER

# 归档目录名（与 OriginalFiles 标准结构一致，大小写规范）
SOURCE_DIR_MAP = {
    "cad": "CAD", "word": "Word", "excel": "Excel", "pdf": "PDF",
    "project": "Project", "image": "Images", "other": "Other",
}

# 是否保留 OriginalFiles 物理副本（2026-08-31 新增）
#   CADKB_KEEP_ARCHIVE_COPY=1 -> 复制副本（旧行为）
#   默认/其他值            -> 不复制，仅记录理论归档路径
KEEP_ARCHIVE_COPY = os.environ.get("CADKB_KEEP_ARCHIVE_COPY", "0") == "1"


def source_type_for_file(path: str | Path) -> SourceType:
    """Map a file's extension to its source category."""
    ext = Path(path).suffix.lower()
    return EXT_TO_SOURCE.get(ext, DEFAULT_SOURCE)


def _to_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _from_json(value: str | None):
    if not value:
        return {}
    try:
        return json.loads(value)
    except Exception:
        return {}


class FileRegistry:
    """Unified file registry service."""

    def __init__(self, session=None, archive_root: Path | None = None):
        if session is not None:
            self.session = session
        else:
            self.session = get_session()
        self._owns_session = session is None
        # archive_root 默认 = config.raw_dir（OriginalFiles 层）
        if archive_root is not None:
            self.archive_root = Path(archive_root)
        else:
            from src.core.config import get_config

            self.archive_root = get_config().raw_dir

    def close(self):
        if self._owns_session:
            self.session.close()

    # ── register ─────────────────────────────────────────────────────

    def register_file(
        self,
        path: str | Path,
        drawing_id: str = "",
        parser: str = "",
        parse_status: str = ParseStatus.PENDING.value,
        extra: dict | None = None,
    ) -> dict:
        """Register a file into the unified registry.

        Dedup by SHA256; archive a copy; record multiple sources;
        create a new version if content changed.
        """
        p = Path(path).resolve()
        if not p.exists():
            return {"status": "error", "message": f"文件不存在: {p}"}

        try:
            sha256 = compute_sha256(p)
        except Exception as e:
            return {"status": "error", "message": f"哈希失败: {e}"}

        info = get_file_info(p)
        if "error" in info:
            return {"status": "error", "message": info["error"]}

        file_type = info["file_type"]
        source_type = source_type_for_file(p).value
        size = info["file_size"]

        # 1. Find by sha256 (dedup)
        existing = (
            self.session.query(FileModel)
            .filter(FileModel.sha256 == sha256)
            .first()
        )

        if existing:
            # 2a. Same content: record additional source
            self._add_source(existing.file_id, str(p))
            logger.info(f"重复文件（同内容），登记新来源: {p.name}")
            return {
                "status": "duplicate",
                "file_id": existing.file_id,
                "sha256": sha256,
                "file_name": existing.original_name,
                "message": "内容相同，已登记新来源路径",
            }

        # 2b. New content: archive copy + register
        archive_rel = self._archive_copy(p, source_type, sha256)
        if archive_rel is None:
            return {"status": "error", "message": "副本复制失败"}

        # 2b.1 非破坏式版本管理（阶段1）：
        #       同名同路径历史记录保留；新内容登记为独立文件，版本号递增，
        #       extra 记录 prev_file_id 用于追溯（不做有效版本判定）。
        version_no = 1
        prev_file_id = ""
        prev_rec = (
            self.session.query(FileModel)
            .filter(FileModel.original_path == str(p))
            .order_by(FileModel.import_time.desc())
            .first()
        )
        if prev_rec and prev_rec.sha256 != sha256:
            prev_file_id = prev_rec.file_id
            prev_versions = (
                self.session.query(FileVersionModel)
                .filter(FileVersionModel.file_id == prev_rec.file_id)
                .count()
            )
            version_no = max(prev_versions, 1) + 1
            logger.info(
                f"检测到同名内容变化（新版本）: {p.name} "
                f"v{version_no} (旧 {prev_file_id[:8]})")

        file_id = self._gen_file_id()
        now = datetime.now()
        meta = dict(extra or {})
        if prev_file_id:
            meta["version_no"] = version_no
            meta["prev_file_id"] = prev_file_id
        rec = FileModel(
            file_id=file_id,
            sha256=sha256,
            original_name=p.name,
            original_path=str(p),
            archive_path=str(archive_rel),
            file_type=file_type,
            source_type=source_type,
            file_size=size,
            created_time=(
                datetime.fromtimestamp(info["created_time"])
                if info.get("created_time") else None
            ),
            modified_time=(
                datetime.fromtimestamp(info["modified_time"])
                if info.get("modified_time") else None
            ),
            import_time=now,
            drawing_id=drawing_id,
            parser=parser,
            parse_status=parse_status,
            parse_time=now if parse_status != ParseStatus.PENDING.value else None,
            extra=_to_json(meta),
        )
        self.session.add(rec)

        # First version
        self.session.add(FileVersionModel(
            version_id=self._gen_file_id(),
            file_id=file_id,
            version_no=version_no,
            sha256=sha256,
            archive_path=str(archive_rel),
            file_size=size,
            modified_time=rec.modified_time,
            parse_status=parse_status,
            created_at=now,
        ))
        # First source
        self._add_source(file_id, str(p))
        self.session.commit()

        logger.info(f"文件已登记: {p.name} file_id={file_id} type={file_type} sha={sha256[:12]}")
        return {
            "status": "success",
            "file_id": file_id,
            "sha256": sha256,
            "file_name": p.name,
            "file_type": file_type,
            "source_type": source_type,
            "archive_path": str(archive_rel),
            "version_no": version_no,
            "prev_file_id": prev_file_id or None,
        }

    def update_parse_status(
        self, file_id: str, status: str, parser: str = ""
    ) -> None:
        """Update parse status after actual parsing."""
        rec = self.session.query(FileModel).filter(
            FileModel.file_id == file_id).first()
        if rec:
            rec.parse_status = status
            rec.parse_time = datetime.now()
            if parser:
                rec.parser = parser
            # update latest version status too
            v = (
                self.session.query(FileVersionModel)
                .filter(FileVersionModel.file_id == file_id)
                .order_by(FileVersionModel.version_no.desc())
                .first()
            )
            if v:
                v.parse_status = status
            self.session.commit()

    def link_drawing(self, file_id: str, drawing_id: str) -> None:
        """Associate a CAD drawing_id with a file record."""
        rec = self.session.query(FileModel).filter(
            FileModel.file_id == file_id).first()
        if rec:
            rec.drawing_id = drawing_id
            self.session.commit()

    def register_metadata_only(
        self,
        original_name: str,
        original_path: str,
        sha256: str,
        file_type: str,
        file_size: int = 0,
        drawing_id: str = "",
        parser: str = "",
        parse_status: str = ParseStatus.PENDING.value,
    ) -> str | None:
        """Register a file without an archive copy (original file missing).

        Used by backfill when the original file no longer exists at the
        recorded path. The KB record is still created (no data fabricated);
        parse_status reflects whatever was recorded historically.
        """
        existing = (
            self.session.query(FileModel)
            .filter(FileModel.sha256 == sha256)
            .first()
        )
        if existing:
            if drawing_id and not existing.drawing_id:
                existing.drawing_id = drawing_id
                self.session.commit()
            return existing.file_id

        source_type = source_type_for_file(original_path).value
        file_id = self._gen_file_id()
        now = datetime.now()
        rec = FileModel(
            file_id=file_id,
            sha256=sha256,
            original_name=original_name,
            original_path=original_path,
            archive_path="",          # no copy available
            file_type=file_type,
            source_type=source_type,
            file_size=file_size,
            import_time=now,
            drawing_id=drawing_id,
            parser=parser,
            parse_status=parse_status,
            parse_time=now if parse_status != ParseStatus.PENDING.value else None,
        )
        self.session.add(rec)
        self.session.add(FileVersionModel(
            version_id=self._gen_file_id(),
            file_id=file_id, version_no=1, sha256=sha256,
            archive_path="", file_size=file_size, parse_status=parse_status,
        ))
        self._add_source(file_id, original_path)
        self.session.commit()
        return file_id

    # ── query ────────────────────────────────────────────────────────

    def get_file(self, file_id: str) -> FileModel | None:
        return (
            self.session.query(FileModel)
            .filter(FileModel.file_id == file_id)
            .first()
        )

    def get_file_by_drawing(self, drawing_id: str) -> FileModel | None:
        return (
            self.session.query(FileModel)
            .filter(FileModel.drawing_id == drawing_id)
            .first()
        )

    def get_original_path(self, file_id: str) -> str | None:
        """Return the archived copy path (KB-owned, independent of origin)."""
        rec = self.get_file(file_id)
        return rec.archive_path if rec else None

    def list_sources(self, file_id: str) -> list[str]:
        rows = (
            self.session.query(FileSourceModel)
            .filter(FileSourceModel.file_id == file_id)
            .all()
        )
        return [r.original_path for r in rows]

    def list_files(
        self,
        source_type: str | None = None,
        file_type: str | None = None,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        q = self.session.query(FileModel)
        if source_type:
            q = q.filter(FileModel.source_type == source_type)
        if file_type:
            q = q.filter(FileModel.file_type == file_type)
        if project_id:
            q = q.filter(FileModel.project_id == project_id)
        if status:
            q = q.filter(FileModel.parse_status == status)
        rows = q.order_by(FileModel.import_time.desc()).offset(offset).limit(limit).all()
        return [self._to_dict(r) for r in rows]

    def search_files(self, keyword: str, limit: int = 50) -> list[dict]:
        """Search files by name (filename keyword match)."""
        kw = f"%{keyword}%"
        rows = (
            self.session.query(FileModel)
            .filter(FileModel.original_name.like(kw))
            .order_by(FileModel.import_time.desc())
            .limit(limit)
            .all()
        )
        return [self._to_dict(r) for r in rows]

    def count_files(self) -> dict:
        from sqlalchemy import func

        total = self.session.query(func.count(FileModel.file_id)).scalar() or 0
        by_type = dict(
            self.session.query(FileModel.source_type,
                               func.count(FileModel.file_id))
            .group_by(FileModel.source_type).all()
        )
        return {"total": total, "by_type": by_type}

    # ── projects ─────────────────────────────────────────────────────

    def get_or_create_project(
        self, name: str, confidence: float = 0.0, source: str = ""
    ) -> ProjectModel | None:
        """Find project by exact name, or create (auto-infer w/ confidence)."""
        name = (name or "").strip()
        if not name:
            return None
        proj = (
            self.session.query(ProjectModel)
            .filter(ProjectModel.name == name)
            .first()
        )
        if proj:
            return proj
        proj = ProjectModel(
            project_id=self._gen_file_id(),
            name=name,
            confidence=confidence,
            source=source or "inferred",
        )
        self.session.add(proj)
        self.session.commit()
        return proj

    def assign_project(self, file_id: str, project_id: str) -> None:
        rec = self.get_file(file_id)
        if rec:
            rec.project_id = project_id
            self.session.commit()

    def list_projects(self) -> list[dict]:
        rows = self.session.query(ProjectModel).order_by(ProjectModel.name).all()
        return [
            {
                "project_id": r.project_id,
                "name": r.name,
                "confidence": r.confidence,
                "source": r.source,
            }
            for r in rows
        ]

    # ── relations / versions ─────────────────────────────────────────

    def add_relation(
        self, file_a: str, file_b: str,
        relation_type: str, confidence: float = 1.0, source: str = "computed",
    ) -> None:
        existing = (
            self.session.query(FileRelationModel)
            .filter(FileRelationModel.file_a == file_a,
                    FileRelationModel.file_b == file_b,
                    FileRelationModel.relation_type == relation_type)
            .first()
        )
        if existing:
            return
        self.session.add(FileRelationModel(
            rel_id=self._gen_file_id(),
            file_a=file_a, file_b=file_b,
            relation_type=relation_type,
            confidence=confidence, source=source,
        ))
        self.session.commit()

    def list_relations(self, file_id: str) -> list[dict]:
        rows = (
            self.session.query(FileRelationModel)
            .filter((FileRelationModel.file_a == file_id)
                    | (FileRelationModel.file_b == file_id))
            .all()
        )
        return [
            {
                "rel_id": r.rel_id,
                "file_a": r.file_a,
                "file_b": r.file_b,
                "relation_type": r.relation_type,
                "confidence": r.confidence,
                "source": r.source,
            }
            for r in rows
        ]

    def list_versions(self, file_id: str) -> list[dict]:
        rows = (
            self.session.query(FileVersionModel)
            .filter(FileVersionModel.file_id == file_id)
            .order_by(FileVersionModel.version_no.desc())
            .all()
        )
        return [
            {
                "version_no": r.version_no,
                "sha256": r.sha256,
                "archive_path": r.archive_path,
                "file_size": r.file_size,
                "parse_status": r.parse_status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    # ── internals ────────────────────────────────────────────────────

    def _archive_copy(self, path: Path, source_type: str, sha256: str) -> Path | None:
        """Copy file into OriginalFiles/<SourceType>/<sha256>.<ext>.

        2026-08-31：受 CADKB_KEEP_ARCHIVE_COPY 控制
          开(=1) -> 复制物理副本（旧行为）
          关(默认) -> 不复制，仅返回理论路径，供 archive_path 字段记录
        """
        dir_name = SOURCE_DIR_MAP.get(source_type, source_type)
        ext = path.suffix.lower() or ".bin"
        dest = self.archive_root / dir_name / f"{sha256}{ext}"

        if not KEEP_ARCHIVE_COPY:
            # 副本不再保留：只记路径，不落盘（解析产物仍完整存入 cadkb.db）
            logger.debug(f"副本已跳过（CADKB_KEEP_ARCHIVE_COPY=0）: {path.name}")
            return dest

        dest_dir = self.archive_root / dir_name
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            if dest.exists() and dest.stat().st_size == path.stat().st_size:
                return dest  # already archived
            shutil.copy2(path, dest)
            return dest
        except Exception as e:
            logger.error(f"副本复制失败: {path.name} -> {dest} - {e}")
            return None

    def _add_source(self, file_id: str, original_path: str) -> None:
        exists = (
            self.session.query(FileSourceModel)
            .filter(FileSourceModel.file_id == file_id,
                    FileSourceModel.original_path == original_path)
            .first()
        )
        if not exists:
            self.session.add(FileSourceModel(
                source_id=self._gen_file_id(),
                file_id=file_id,
                original_path=original_path,
            ))
            self.session.commit()

    @staticmethod
    def _gen_file_id() -> str:
        import uuid
        return str(uuid.uuid4())

    @staticmethod
    def _to_dict(r: FileModel) -> dict:
        return {
            "file_id": r.file_id,
            "sha256": r.sha256,
            "file_name": r.original_name,
            "original_path": r.original_path,
            "archive_path": r.archive_path,
            "file_type": r.file_type,
            "source_type": r.source_type,
            "file_size": r.file_size,
            "import_time": r.import_time.isoformat() if r.import_time else None,
            "project_id": r.project_id,
            "category": r.category,
            "tags": _from_json(r.tags) if r.tags else [],
            "parser": r.parser,
            "parse_status": r.parse_status,
            "parse_time": r.parse_time.isoformat() if r.parse_time else None,
            "drawing_id": r.drawing_id,
        }


def register_file(path, **kwargs) -> dict:
    """Convenience wrapper."""
    reg = FileRegistry()
    try:
        return reg.register_file(path, **kwargs)
    finally:
        reg.close()


def get_file(file_id: str) -> FileModel | None:
    reg = FileRegistry()
    try:
        return reg.get_file(file_id)
    finally:
        reg.close()


def get_original_file(file_id: str) -> str | None:
    """Return the KB archive copy path for a file_id."""
    reg = FileRegistry()
    try:
        return reg.get_original_path(file_id)
    finally:
        reg.close()
