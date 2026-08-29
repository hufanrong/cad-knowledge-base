"""Unit tests for Phase 3: Semantic analysis.

Covers:
1. Frame detection (图框识别)
2. Title block extraction (标题栏提取)
3. Equipment extraction (设备识别)
4. Pipe extraction (管道识别)
5. Database persistence of semantic results
6. Import integration (importer runs semantic analysis)
"""

import pytest


def _parse_and_analyze(dxf_path):
    """Helper: parse a DXF and run semantic analysis."""
    from src.parsers.dxf_parser import DXFParser
    from src.semantic import analyze

    parser = DXFParser()
    result = parser.parse(dxf_path)
    assert result.drawing.parse_status == "success"
    return analyze(result)


class TestFrameDetection:
    """Test drawing frame (图框) detection."""

    def test_detect_frame_from_lines(self, test_dxf_all):
        """Test frame detection from 4 LINE entities."""
        result = _parse_and_analyze(test_dxf_all)
        assert len(result.frames) >= 1, "Should detect at least one frame"
        frame = result.frames[0]
        assert frame.bounding_box.width == pytest.approx(1000.0, rel=0.05)
        assert frame.bounding_box.height == pytest.approx(500.0, rel=0.05)
        assert frame.entity_count == 4
        assert frame.confidence > 0.5
        assert frame.source == "rule_based"

    def test_no_frame_in_simple_file(self, test_dxf_simple):
        """Test that a file without a frame yields no frame."""
        result = _parse_and_analyze(test_dxf_simple)
        # simple file has no 4-line rectangle => 0 frames
        assert len(result.frames) == 0


class TestTitleBlock:
    """Test title block (标题栏) extraction."""

    def test_extract_title_block(self, test_dxf_all):
        """Test extracting title block fields."""
        result = _parse_and_analyze(test_dxf_all)
        assert len(result.title_blocks) >= 1, "Should detect a title block"
        tb = result.title_blocks[0]
        assert len(tb.fields) >= 3, f"Expected >=3 fields, got {len(tb.fields)}"

        fields = {f.key: f.value for f in tb.fields}
        assert fields.get("图号") == "2024-001"
        assert "图纸名称" in fields or "图名" in fields
        assert fields.get("比例") == "1:100"

        # All fields carry confidence and are rule-based
        for f in tb.fields:
            assert f.confidence > 0.0
            assert f.source == "rule_based"


class TestEquipmentExtraction:
    """Test equipment (设备) extraction."""

    def test_extract_equipment(self, test_dxf_all):
        """Test extracting equipment from block attributes."""
        result = _parse_and_analyze(test_dxf_all)
        assert len(result.equipment) >= 2, f"Expected >=2 equipment, got {len(result.equipment)}"

        # Equipment no+name merged from attributes
        eq_map = {e.equipment_no: e for e in result.equipment if e.equipment_no}
        assert "MILL-001" in eq_map
        assert eq_map["MILL-001"].equipment_name == "球磨机"
        assert eq_map["MILL-001"].confidence >= 0.8

        names = [e.equipment_name for e in result.equipment if e.equipment_name]
        assert "酸化窑" in names


class TestPipeExtraction:
    """Test pipe (管道) extraction."""

    def test_extract_pipe_diameter(self, test_dxf_all):
        """Test extracting pipe diameter from text."""
        result = _parse_and_analyze(test_dxf_all)
        assert len(result.pipes) >= 1, "Should detect at least one pipe"

        diameters = [p.diameter for p in result.pipes if p.diameter]
        assert any("φ4500" in d for d in diameters), f"No φ4500 found: {diameters}"

    def test_no_false_material(self, test_dxf_all):
        """Test that dimension numbers are NOT mis-detected as material."""
        result = _parse_and_analyze(test_dxf_all)
        # "45" inside φ4500×45000 must NOT be flagged as material 45#
        for p in result.pipes:
            assert p.material not in ("45", "20"), f"False material: {p.material}"


class TestSemanticDatabase:
    """Test semantic results persistence and query."""

    def test_save_and_query_semantic(self, test_dxf_all, tmp_path):
        """Test that semantic results are saved and queryable."""
        from src.core.config import get_config
        from src.database.connection import get_session, init_database, reset_engine
        from src.database.repositories import DrawingRepository
        from src.file_manager.hasher import compute_sha256
        from src.parsers.dxf_parser import DXFParser
        from src.semantic import analyze

        config = get_config()
        config.db_path = tmp_path / "test_semantic.db"
        config.ensure_directories()
        reset_engine()
        init_database()

        result = DXFParser().parse(test_dxf_all)
        result.drawing.file_hash = compute_sha256(test_dxf_all)
        result.drawing.file_size = test_dxf_all.stat().st_size
        analyze(result)

        session = get_session()
        repo = DrawingRepository(session)
        drawing_id = repo.save_parse_result(result)
        session.close()

        session = get_session()
        repo = DrawingRepository(session)

        assert len(repo.get_frames_by_drawing(drawing_id)) >= 1

        tbs = repo.get_title_blocks_by_drawing(drawing_id)
        assert len(tbs) >= 1
        assert any(f["key"] == "图号" for f in tbs[0]["fields"])

        eqs = repo.get_equipment_by_drawing(drawing_id)
        assert len(eqs) >= 2

        pipes = repo.get_pipes_by_drawing(drawing_id)
        assert len(pipes) >= 1

        # Stats include semantic counts
        stats = repo.get_database_stats()
        assert stats["frames"] >= 1
        assert stats["equipment"] >= 2

        session.close()

    def test_import_runs_semantic(self, test_dxf_all, tmp_path):
        """Test that the import pipeline runs semantic analysis."""
        from src.core.config import get_config
        from src.database.connection import get_session, reset_engine
        from src.database.repositories import DrawingRepository
        from src.file_manager.importer import import_file

        config = get_config()
        config.db_path = tmp_path / "test_import_semantic.db"
        config.ensure_directories()
        reset_engine()

        result = import_file(test_dxf_all)
        assert result["status"] == "success"

        drawing_id = result["drawing_id"]
        session = get_session()
        repo = DrawingRepository(session)
        assert len(repo.get_frames_by_drawing(drawing_id)) >= 1
        assert len(repo.get_title_blocks_by_drawing(drawing_id)) >= 1
        assert len(repo.get_equipment_by_drawing(drawing_id)) >= 2
        session.close()


class TestSemanticDWG:
    """Test semantic analysis on DWG files (integration with ODA)."""

    def test_semantic_dwg(self, test_dwg_all):
        """Test semantic analysis works on DWG-parsed data."""
        from src.parsers.oda_converter import is_oda_available
        if not is_oda_available():
            pytest.skip("ODA File Converter 未安装，跳过 DWG 语义测试")
        from src.parsers.dwg_parser import DWGParser
        from src.semantic import analyze

        result = DWGParser().parse(test_dwg_all)
        assert result.drawing.parse_status == "success"
        analyze(result)

        assert len(result.frames) >= 1, "DWG should also have a frame"
        assert len(result.title_blocks) >= 1, "DWG should also have a title block"
        assert len(result.equipment) >= 2
        # Text content survives: pipe diameter present
        diameters = [p.diameter for p in result.pipes if p.diameter]
        assert any("φ4500" in d for d in diameters)
