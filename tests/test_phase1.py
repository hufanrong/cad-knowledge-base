"""Unit tests for the CAD Knowledge Base Phase 1 modules."""

import pytest
from pathlib import Path


class TestVersionDetector:
    """Test file type and version detection."""

    def test_detect_dxf_file_type(self, test_dxf_simple):
        """Test DXF file type detection."""
        from src.file_manager.version_detector import detect_file_type, FileType
        ft = detect_file_type(test_dxf_simple)
        assert ft == FileType.DXF

    def test_detect_dxf_version(self, test_dxf_simple):
        """Test DXF version detection."""
        from src.file_manager.version_detector import detect_dxf_version
        code, name = detect_dxf_version(test_dxf_simple)
        assert code.startswith("AC"), f"Expected AC-prefixed version, got: {code}"
        assert "AutoCAD" in name or "Unknown" in name

    def test_get_file_info(self, test_dxf_simple):
        """Test comprehensive file info extraction."""
        from src.file_manager.version_detector import get_file_info
        info = get_file_info(test_dxf_simple)
        assert info["file_name"] == "test_simple.dxf"
        assert info["file_type"] == "dxf"
        assert info["file_size"] > 0
        assert "cad_version" in info


class TestHasher:
    """Test file hashing."""

    def test_sha256_consistent(self, test_dxf_simple):
        """Test that SHA256 is consistent for the same file."""
        from src.file_manager.hasher import compute_sha256
        h1 = compute_sha256(test_dxf_simple)
        h2 = compute_sha256(test_dxf_simple)
        assert h1 == h2
        assert len(h1) == 64  # SHA256 hex length

    def test_sha256_different_files(self, test_dxf_simple, test_dxf_all):
        """Test that different files have different hashes."""
        from src.file_manager.hasher import compute_sha256
        h1 = compute_sha256(test_dxf_simple)
        h2 = compute_sha256(test_dxf_all)
        assert h1 != h2


class TestDXFParser:
    """Test DXF parsing with ezdxf."""

    def test_parse_simple_dxf(self, test_dxf_simple):
        """Test parsing a simple DXF file."""
        from src.parsers.dxf_parser import DXFParser
        parser = DXFParser()
        assert parser.can_parse(test_dxf_simple)

        result = parser.parse(test_dxf_simple)
        assert result.drawing.parse_status == "success"
        assert result.drawing.cad_version.startswith("AC")
        assert result.drawing.units == "mm"
        assert len(result.entities) > 0
        assert len(result.layers) > 0

    def test_parse_all_entities(self, test_dxf_all):
        """Test parsing a DXF file with all entity types."""
        from src.parsers.dxf_parser import DXFParser
        parser = DXFParser()
        result = parser.parse(test_dxf_all)

        assert result.drawing.parse_status == "success"

        # Check entity types present
        entity_types = {e.entity_type for e in result.entities}
        assert "LINE" in entity_types, f"LINE not found. Types: {entity_types}"
        assert "CIRCLE" in entity_types
        assert "ARC" in entity_types
        assert "LWPOLYLINE" in entity_types
        assert "SPLINE" in entity_types
        assert "ELLIPSE" in entity_types
        assert "TEXT" in entity_types
        assert "MTEXT" in entity_types
        assert "INSERT" in entity_types

        # Check texts extracted
        assert len(result.texts) > 0
        text_contents = [t.text_content for t in result.texts]
        assert any("酸化窑" in t for t in text_contents), "Chinese text not found"
        assert any("MILL-001" in t for t in text_contents)

        # Check dimensions extracted
        assert len(result.dimensions) > 0
        dim_types = {d.dimension_type for d in result.dimensions}
        assert "linear" in dim_types or "aligned" in dim_types

        # Check block attributes extracted
        assert len(result.attributes) > 0
        tags = {a.tag for a in result.attributes}
        assert "EQUIP_NO" in tags
        assert "EQUIP_NAME" in tags

        # Check values
        equip_names = [a.value for a in result.attributes if a.tag == "EQUIP_NAME"]
        assert "球磨机" in equip_names

    def test_mtext_code_stripping(self, test_dxf_all):
        """Test that MTEXT formatting codes are stripped."""
        from src.parsers.dxf_parser import DXFParser
        parser = DXFParser()
        result = parser.parse(test_dxf_all)

        # Find the MTEXT with formatting codes
        mtexts = [t for t in result.texts if t.text_type == "MTEXT"]
        assert len(mtexts) >= 2

        # The second MTEXT has formatting codes
        formatted = [t for t in mtexts if t.raw_text and "\\" in t.raw_text]
        if formatted:
            # Clean text should not contain backslash codes
            assert "{" not in formatted[0].text_content
            assert "\\C" not in formatted[0].text_content

    def test_bounding_box_computation(self, test_dxf_all):
        """Test that bounding boxes are computed for entities."""
        from src.parsers.dxf_parser import DXFParser
        parser = DXFParser()
        result = parser.parse(test_dxf_all)

        lines = [e for e in result.entities if e.entity_type == "LINE"]
        assert len(lines) > 0
        for line in lines:
            bbox = line.bounding_box
            assert bbox.width >= 0
            assert bbox.height >= 0

        circles = [e for e in result.entities if e.entity_type == "CIRCLE"]
        for circle in circles:
            bbox = circle.bounding_box
            assert bbox.width > 0  # Circle has non-zero width

    def test_quality_report(self, test_dxf_all):
        """Test that quality report is generated."""
        from src.parsers.dxf_parser import DXFParser
        parser = DXFParser()
        result = parser.parse(test_dxf_all)

        assert result.quality_report is not None
        assert result.quality_report.entity_count > 0
        assert result.quality_report.text_count > 0
        assert result.quality_report.dimension_count > 0
        assert result.quality_report.data_completeness > 0.0
        assert result.quality_report.unit_detected  # mm detected

    def test_parse_r12(self, test_dxf_r12):
        """Test parsing R12 DXF version."""
        from src.parsers.dxf_parser import DXFParser
        parser = DXFParser()
        result = parser.parse(test_dxf_r12)
        assert result.drawing.parse_status == "success"
        assert len(result.entities) > 0

    def test_parse_r2000(self, test_dxf_r2000):
        """Test parsing R2000 DXF version."""
        from src.parsers.dxf_parser import DXFParser
        parser = DXFParser()
        result = parser.parse(test_dxf_r2000)
        assert result.drawing.parse_status == "success"
        assert len(result.entities) > 0


class TestDatabase:
    """Test database operations."""

    def test_init_database(self, tmp_path):
        """Test database initialization."""
        from src.core.config import get_config
        from src.database.connection import init_database, get_engine

        config = get_config()
        config.db_path = tmp_path / "test.db"
        config.ensure_directories()

        init_database()
        engine = get_engine()

        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "drawings" in tables
        assert "entities" in tables
        assert "texts" in tables
        assert "dimensions" in tables
        assert "layers" in tables

    def test_save_and_query(self, test_dxf_simple, tmp_path):
        """Test saving parse result and querying it back."""
        from src.core.config import get_config
        from src.database.connection import init_database, get_session
        from src.database.repositories import DrawingRepository
        from src.file_manager.hasher import compute_sha256
        from src.parsers.dxf_parser import DXFParser

        config = get_config()
        config.db_path = tmp_path / "test.db"
        config.ensure_directories()
        init_database()

        # Parse
        parser = DXFParser()
        result = parser.parse(test_dxf_simple)
        result.drawing.file_hash = compute_sha256(test_dxf_simple)
        result.drawing.file_size = Path(test_dxf_simple).stat().st_size

        # Save
        session = get_session()
        repo = DrawingRepository(session)
        drawing_id = repo.save_parse_result(result)
        session.close()

        assert drawing_id is not None

        # Query
        session = get_session()
        repo = DrawingRepository(session)

        # Check drawing exists
        draw = repo.find_by_id(drawing_id)
        assert draw is not None
        assert draw.file_name == "test_simple.dxf"
        assert draw.entity_count > 0

        # Check entities
        entities = repo.get_entities_by_drawing(drawing_id)
        assert len(entities) > 0

        # Check texts
        texts = repo.get_texts_by_drawing(drawing_id)
        assert len(texts) > 0
        assert any("Hello CAD" in t["text_content"] for t in texts)

        # Check duplicate detection
        existing = repo.find_by_hash(result.drawing.file_hash)
        assert existing is not None

        session.close()

    def test_fulltext_search(self, test_dxf_all, tmp_path):
        """Test full-text search."""
        from src.core.config import get_config
        from src.database.connection import init_database, get_session
        from src.database.repositories import DrawingRepository
        from src.file_manager.hasher import compute_sha256
        from src.parsers.dxf_parser import DXFParser

        config = get_config()
        config.db_path = tmp_path / "test.db"
        config.ensure_directories()
        init_database()

        # Parse and save
        parser = DXFParser()
        result = parser.parse(test_dxf_all)
        result.drawing.file_hash = compute_sha256(test_dxf_all)
        result.drawing.file_size = Path(test_dxf_all).stat().st_size

        session = get_session()
        repo = DrawingRepository(session)
        drawing_id = repo.save_parse_result(result)
        session.close()

        # Search
        session = get_session()
        repo = DrawingRepository(session)
        results = repo.search_fulltext("酸化窑")
        assert len(results) > 0
        assert any("酸化窑" in r["text_content"] for r in results)

        session.close()


class TestImporter:
    """Test file import flow."""

    def test_import_dxf(self, test_dxf_simple, tmp_path):
        """Test importing a DXF file end-to-end."""
        from src.core.config import get_config
        from src.database.connection import reset_engine
        from src.file_manager.importer import import_file

        config = get_config()
        config.db_path = tmp_path / "test_import.db"
        config.ensure_directories()
        reset_engine()

        result = import_file(test_dxf_simple)
        assert result["status"] == "success"
        assert result["entity_count"] > 0
        assert "drawing_id" in result

    def test_import_duplicate(self, test_dxf_simple, tmp_path):
        """Test that importing the same file twice returns duplicate."""
        from src.core.config import get_config
        from src.database.connection import reset_engine
        from src.file_manager.importer import import_file

        config = get_config()
        config.db_path = tmp_path / "test_dup.db"
        config.ensure_directories()
        reset_engine()

        # First import
        result1 = import_file(test_dxf_simple)
        assert result1["status"] == "success"

        # Second import (should be duplicate)
        result2 = import_file(test_dxf_simple)
        assert result2["status"] == "duplicate"

    def test_import_nonexistent(self, tmp_path):
        """Test importing a non-existent file."""
        from src.core.config import get_config
        from src.file_manager.importer import import_file

        config = get_config()
        config.db_path = tmp_path / "test.db"
        config.ensure_directories()

        result = import_file("nonexistent.dxf")
        assert result["status"] == "error"
