"""Unit tests for Phase 8: CAD version compatibility.

Covers:
1. Version detection for all supported DWG versions
2. Multi-version DXF parsing (R12/R2000/R2004/R2007/R2010/R2013/R2018)
3. Multi-version DWG parsing (via ODA)
4. Import + semantic analysis across versions
5. AutoCAD COM fallback availability checks
"""

import pytest

from tests.conftest import TEST_DWG_DIR

# (fixture name, expected DXF version code, expected name)
DXF_VERSIONS = [
    ("test_r12.dxf", "AC1009", "R12"),
    ("test_r2000.dxf", "AC1015", "R2000"),
    ("test_r2004.dxf", "AC1018", "R2004"),
    ("test_r2007.dxf", "AC1021", "R2007"),
    ("test_r2010.dxf", "AC1024", "R2010"),
    ("test_r2013.dxf", "AC1027", "R2013"),
    ("test_all_entities.dxf", "AC1032", "R2018"),
]

# (fixture name, expected DWG header, expected name)
DWG_VERSIONS = [
    ("test_r12.dwg", "AC1009", "R12"),
    ("test_r2000.dwg", "AC1015", "R2000"),
    ("test_r2004.dwg", "AC1018", "R2004"),
    ("test_r2007.dwg", "AC1021", "R2007"),
    ("test_r2010.dwg", "AC1024", "R2010"),
    ("test_r2013.dwg", "AC1027", "R2013"),
    ("test_all_entities.dwg", "AC1032", "R2018"),
]


class TestVersionDetection:
    """Test version identification from file headers."""

    def test_dxf_version_detection(self):
        """Test DXF version detection across all versions."""
        from src.file_manager.version_detector import detect_dxf_version
        from tests.conftest import TEST_DXF_DIR

        for fname, code, name in DXF_VERSIONS:
            path = TEST_DXF_DIR / fname
            assert path.exists(), f"Missing fixture {fname}"
            ver_code, ver_name = detect_dxf_version(path)
            assert ver_code == code, f"{fname}: expected {code}, got {ver_code}"

    def test_dwg_version_detection(self):
        """Test DWG version detection from file header."""
        from src.file_manager.version_detector import detect_dwg_version

        for fname, code, name in DWG_VERSIONS:
            path = TEST_DWG_DIR / fname
            assert path.exists(), f"Missing fixture {fname}"
            ver_code, ver_name = detect_dwg_version(path)
            assert ver_code == code, f"{fname}: expected {code}, got {ver_code}"


class TestMultiVersionDXF:
    """Test DXF parsing across versions."""

    @pytest.mark.parametrize("fname,code,name", DXF_VERSIONS)
    def test_parse_all_versions(self, fname, code, name):
        """Test that each DXF version parses successfully."""
        from src.parsers.dxf_parser import DXFParser
        from tests.conftest import TEST_DXF_DIR

        path = TEST_DXF_DIR / fname
        result = DXFParser().parse(path)
        assert result.drawing.parse_status == "success", f"{name} parse failed"
        assert result.drawing.cad_version == code
        assert len(result.entities) > 0
        assert len(result.layers) > 0

    def test_quality_similar_across_versions(self):
        """Test that data completeness is similar across versions."""
        from src.parsers.dxf_parser import DXFParser
        from tests.conftest import TEST_DXF_DIR

        scores = {}
        for fname, code, name in DXF_VERSIONS:
            result = DXFParser().parse(TEST_DXF_DIR / fname)
            scores[name] = result.drawing.data_completeness

        # All versions should have decent completeness
        for name, score in scores.items():
            assert score >= 0.5, f"{name} completeness too low: {score}"


class TestMultiVersionDWG:
    """Test DWG parsing across versions (via ODA)."""

    @pytest.mark.parametrize("fname,code,name", DWG_VERSIONS)
    def test_parse_all_dwg_versions(self, fname, code, name):
        """Test that each DWG version parses successfully."""
        from src.parsers.dwg_parser import DWGParser
        from src.parsers.oda_converter import is_oda_available
        from src.parsers.autocad_com import is_autocad_available

        if not is_oda_available() and not is_autocad_available():
            pytest.skip("ODA 和 AutoCAD COM 均不可用，跳过 DWG 测试")

        path = TEST_DWG_DIR / fname
        result = DWGParser().parse(path)
        assert result.drawing.parse_status == "success", f"{name} parse failed"
        assert result.drawing.cad_version == code, (
            f"{name}: expected {code}, got {result.drawing.cad_version}"
        )
        assert len(result.entities) > 0


class TestVersionCompatibilityFull:
    """Test full pipeline across versions."""

    @pytest.mark.parametrize("fname,code,name", DXF_VERSIONS)
    def test_import_and_semantic(self, fname, code, name, tmp_path):
        """Test import + semantic analysis for each DXF version."""
        from src.core.config import get_config
        from src.database.connection import get_session, reset_engine
        from src.database.repositories import DrawingRepository
        from src.file_manager.importer import import_file
        from tests.conftest import TEST_DXF_DIR

        config = get_config()
        config.db_path = tmp_path / f"test_{name}.db"
        config.ensure_directories()
        reset_engine()

        result = import_file(TEST_DXF_DIR / fname)
        assert result["status"] == "success", f"{name} import failed"

        session = get_session()
        repo = DrawingRepository(session)
        # Entities persisted
        ents = repo.get_entities_by_drawing(result["drawing_id"], limit=1)
        assert len(ents) >= 1
        session.close()


class TestAutoCADComFallback:
    """Test AutoCAD COM fallback path availability."""

    def test_is_autocad_available_returns_bool(self):
        """Test that availability check returns a bool, never crashes."""
        from src.parsers.autocad_com import is_autocad_available

        result = is_autocad_available()
        assert isinstance(result, bool)

    def test_convert_missing_file(self):
        """Test that converting a missing file returns None."""
        from src.parsers.autocad_com import convert_dwg_to_dxf

        assert convert_dwg_to_dxf("C:/nonexistent/foo.dwg") is None
