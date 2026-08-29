"""Unit tests for Phase 2: DWG parsing support.

These tests exercise the DWG parsing pipeline:
1. ODA File Converter wrapper (oda_converter.py)
2. DWG parser (dwg_parser.py) — DWG -> DXF -> unified schema
3. End-to-end import of DWG files

Requires ODA File Converter to be installed. If it's not available,
the DWG-specific tests are skipped (with a clear message) so the rest
of the suite still runs.
"""

import pytest

from src.parsers.oda_converter import ODAConverter, is_oda_available

# Module-level check; skip DWG tests entirely if ODA is missing
pytestmark = pytest.mark.skipif(
    not is_oda_available(),
    reason="ODA File Converter 未安装，跳过 DWG 测试",
)


class TestODAConverter:
    """Test the ODA command-line wrapper."""

    def test_detect_oda_path(self):
        """Test that ODA executable is located."""
        exe = ODAConverter().exe_path
        assert exe, "ODA executable path should be non-empty"
        from pathlib import Path

        assert Path(exe).exists(), f"ODA executable should exist: {exe}"

    def test_convert_dwg_to_dxf(self, test_dwg_all, tmp_path):
        """Test DWG -> DXF conversion."""
        converter = ODAConverter()
        out_dxf = converter.convert_dwg_to_dxf(
            dwg_path=test_dwg_all,
            output_dir=tmp_path,
            output_version="ACAD2018",
        )
        assert out_dxf is not None
        assert out_dxf.exists()
        assert out_dxf.suffix.lower() == ".dxf"
        assert out_dxf.stat().st_size > 0

    def test_convert_missing_file(self, tmp_path):
        """Test conversion of a non-existent file raises FileNotFoundError."""
        converter = ODAConverter()
        with pytest.raises(FileNotFoundError):
            converter.convert_dwg_to_dxf(
                dwg_path=tmp_path / "missing.dwg",
                output_dir=tmp_path,
            )


class TestDWGParser:
    """Test DWG parsing via ODA + ezdxf."""

    def test_parser_identity(self):
        """Test parser metadata."""
        from src.parsers.dwg_parser import DWGParser

        parser = DWGParser()
        assert parser.name == "oda+ezdxf"
        assert parser.supported_types == ["dwg"]
        assert parser.can_parse("foo.dwg")
        assert not parser.can_parse("foo.dxf")

    def test_parse_dwg_all_entities(self, test_dwg_all):
        """Test parsing a DWG with all entity types."""
        from src.parsers.dwg_parser import DWGParser

        parser = DWGParser()
        result = parser.parse(test_dwg_all)

        assert result.drawing.parse_status == "success"
        assert result.drawing.file_type == "dwg"
        assert result.drawing.file_name == "test_all_entities.dwg"
        assert result.drawing.parser == "oda+ezdxf"
        assert result.drawing.cad_version.startswith("AC")

        # Same content as the DXF fixture it was generated from
        entity_types = {e.entity_type for e in result.entities}
        assert "LINE" in entity_types
        assert "CIRCLE" in entity_types
        assert "ARC" in entity_types
        assert "LWPOLYLINE" in entity_types
        assert "SPLINE" in entity_types
        assert "ELLIPSE" in entity_types
        assert "TEXT" in entity_types
        assert "MTEXT" in entity_types
        assert "INSERT" in entity_types

        # Texts survive the conversion
        text_contents = [t.text_content for t in result.texts]
        assert any("酸化窑" in t for t in text_contents), "Chinese text lost in DWG conversion"
        assert any("MILL-001" in t for t in text_contents)

        # Dimensions and block attributes survive
        assert len(result.dimensions) > 0
        tags = {a.tag for a in result.attributes}
        assert "EQUIP_NO" in tags
        assert "EQUIP_NAME" in tags

    def test_parse_dwg_r12(self, test_dwg_r12):
        """Test parsing an R12 DWG file."""
        from src.parsers.dwg_parser import DWGParser

        parser = DWGParser()
        result = parser.parse(test_dwg_r12)
        assert result.drawing.parse_status == "success"
        assert result.drawing.cad_version == "AC1009"
        assert len(result.entities) > 0

    def test_parse_dwg_r2000(self, test_dwg_r2000):
        """Test parsing an R2000 DWG file."""
        from src.parsers.dwg_parser import DWGParser

        parser = DWGParser()
        result = parser.parse(test_dwg_r2000)
        assert result.drawing.parse_status == "success"
        assert result.drawing.cad_version == "AC1015"
        assert len(result.entities) > 0


class TestDWGImporter:
    """Test end-to-end DWG import."""

    def test_import_dwg(self, test_dwg_simple, tmp_path):
        """Test importing a DWG file end-to-end."""
        from src.core.config import get_config
        from src.database.connection import reset_engine
        from src.file_manager.importer import import_file

        config = get_config()
        config.db_path = tmp_path / "test_import_dwg.db"
        config.ensure_directories()
        reset_engine()

        result = import_file(test_dwg_simple)
        assert result["status"] == "success", f"Import failed: {result}"
        assert result["file_type"] == "dwg"
        assert result["entity_count"] > 0
        assert "drawing_id" in result

    def test_import_dwg_duplicate(self, test_dwg_simple, tmp_path):
        """Test that importing the same DWG twice returns duplicate."""
        from src.core.config import get_config
        from src.database.connection import reset_engine
        from src.file_manager.importer import import_file

        config = get_config()
        config.db_path = tmp_path / "test_dup_dwg.db"
        config.ensure_directories()
        reset_engine()

        r1 = import_file(test_dwg_simple)
        assert r1["status"] == "success"

        r2 = import_file(test_dwg_simple)
        assert r2["status"] == "duplicate"

    def test_dwg_searchable(self, test_dwg_all, tmp_path):
        """Test that DWG-imported text is searchable."""
        from src.core.config import get_config
        from src.database.connection import get_session, init_database, reset_engine
        from src.database.repositories import DrawingRepository
        from src.file_manager.importer import import_file

        config = get_config()
        config.db_path = tmp_path / "test_search_dwg.db"
        config.ensure_directories()
        reset_engine()

        result = import_file(test_dwg_all)
        assert result["status"] == "success"

        session = get_session()
        repo = DrawingRepository(session)
        hits = repo.search_fulltext("酸化窑")
        session.close()

        assert len(hits) > 0, "DWG-imported Chinese text should be searchable"
