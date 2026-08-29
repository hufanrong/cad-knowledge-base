"""Unit tests for Phase 4: Project(.mpp) fallback, images, PPTX.

Covers:
1. MPP: COM availability detection + graceful fallback (never fabricate)
2. Image parser: dimensions/format metadata
3. PPTX parser: slide text
4. End-to-end import of images/pptx through the pipeline
"""

import pytest


@pytest.fixture(autouse=True)
def doc_kb(tmp_path):
    """Isolated KB."""
    from src.core.config import get_config
    from src.database.connection import init_database, reset_engine
    from src.database.connection import get_session
    from src.database.models import (
        FileModel, FileSourceModel, FileVersionModel,
        ProjectModel, FileRelationModel,
    )

    cfg = get_config()
    cfg.db_path = tmp_path / "p4.db"
    cfg.raw_dir = tmp_path / "OriginalFiles"
    cfg.parsed_dir = tmp_path / "ParsedData"
    cfg.ensure_directories()
    reset_engine()
    init_database()

    session = get_session()
    for m in (FileRelationModel, ProjectModel, FileVersionModel,
              FileSourceModel, FileModel):
        session.query(m).delete()
    session.commit()
    session.close()
    return tmp_path


@pytest.fixture
def pptx_file(tmp_path):
    """Create a small .pptx."""
    from pptx import Presentation

    path = tmp_path / "进度.pptx"
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "设备安装进度"
    s.placeholders[1].text = "进场 -> 吊装 -> 试车"
    prs.save(str(path))
    return path


@pytest.fixture
def png_file(tmp_path):
    """Create a small PNG."""
    from PIL import Image

    path = tmp_path / "photo.png"
    Image.new("RGB", (320, 240), "white").save(str(path))
    return path


class TestProjectParser:
    def test_com_availability_check(self):
        """COM availability returns bool, never crashes."""
        from src.parsers.project_parser import is_ms_project_available

        assert isinstance(is_ms_project_available(), bool)

    def test_invalid_mpp_graceful_fallback(self, tmp_path):
        """Broken .mpp must NOT be faked; marked pending."""
        p = tmp_path / "broken.mpp"
        p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 400)

        from src.parsers.project_parser import ProjectParser

        r = ProjectParser().parse(p)
        assert r.parse_status in ("pending", "failed")
        # No fake data
        assert r.tables == []
        # Clear message about being unparseable
        assert any("不可解析" in e or "COM" in e for e in r.errors)

    def test_import_mpp_keeps_archive(self, doc_kb, tmp_path):
        """Even unparseable MPP is registered + archived."""
        from src.file_manager.importer import import_file

        p = tmp_path / "plan.mpp"
        p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 400)

        r = import_file(p)
        assert r["status"] in ("success", "failed", "pending")
        # If registered, archive copy exists
        if r.get("file_id"):
            from src.core.file_registry import FileRegistry

            reg = FileRegistry()
            rec = reg.get_file(r["file_id"])
            assert rec.archive_path
            assert "Project" in rec.archive_path
            reg.close()


class TestImageParser:
    def test_metadata(self, png_file):
        from src.parsers.image_parser import ImageParser

        r = ImageParser().parse(png_file)
        assert r.parse_status in ("success", "partial")
        assert r.metadata["width"] == 320
        assert r.metadata["height"] == 240
        assert r.metadata["format"] == "PNG"
        assert r.source in ("text", "ocr")  # OCR optional


class TestPPTXParser:
    def test_parse_pptx(self, pptx_file):
        from src.parsers.pptx_parser import PPTXParser

        r = PPTXParser().parse(pptx_file)
        assert r.parse_status == "success"
        assert r.metadata["slide_count"] == 1
        assert len(r.sections) >= 1
        assert "设备安装进度" in r.content
        assert r.source == "text"


class TestImportPipeline:
    def test_import_pptx_and_png(self, doc_kb, pptx_file, png_file):
        from src.file_manager.importer import import_file

        r1 = import_file(pptx_file)
        assert r1["status"] == "success"
        assert r1["source_type"] == "other"

        r2 = import_file(png_file)
        assert r2["status"] == "success"
        assert r2["source_type"] == "image"
        assert r2["title"] == "photo"

        # Archive dirs
        from src.core.file_registry import FileRegistry

        reg = FileRegistry()
        stats = reg.count_files()
        assert stats["total"] == 2
        reg.close()
