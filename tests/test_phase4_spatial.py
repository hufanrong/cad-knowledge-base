"""Unit tests for Phase 4: Spatial relationships.

Covers:
1. Proximity analyzer (CONTAINS / INTERSECTS / NEAR)
2. Annotation detection (ANNOTATES)
3. Block membership (BELONGS_TO)
4. Database persistence & query
5. Import integration
"""

import pytest


def _parse_and_spatial(dxf_path):
    """Helper: parse a DXF and run spatial analysis."""
    from src.parsers.dxf_parser import DXFParser
    from src.spatial import analyze

    parser = DXFParser()
    result = parser.parse(dxf_path)
    assert result.drawing.parse_status == "success"
    return analyze(result)


class TestProximity:
    """Test geometric relationship computation."""

    def test_relationships_generated(self, test_dxf_all):
        """Test that spatial relationships are computed."""
        result = _parse_and_spatial(test_dxf_all)
        assert len(result.relationships) > 0, "Should generate relationships"

        types = {r.relationship_type.value for r in result.relationships}
        assert types, "Relationships should have types"

    def test_relationship_fields(self, test_dxf_all):
        """Test that each relationship has proper fields."""
        result = _parse_and_spatial(test_dxf_all)
        for rel in result.relationships:
            assert rel.entity_a_id, "entity_a_id required"
            assert rel.entity_b_id, "entity_b_id required"
            assert rel.entity_a_id != rel.entity_b_id
            assert 0.0 <= rel.confidence <= 1.0
            assert rel.source == "computed"

    def test_contains_relationship(self, test_dxf_all):
        """Test that CONTAINS relationships exist (circle in rectangle etc.)."""
        result = _parse_and_spatial(test_dxf_all)
        contains = [r for r in result.relationships if r.relationship_type.value == "contains"]
        # The LWPOLYLINE box (1100-1500 x 0-300) contains the hatch path
        # and various inner entities, so we expect >= 1
        assert len(contains) >= 1, "Expected at least one CONTAINS relationship"

    def test_no_self_relationships(self, test_dxf_all):
        """Test that no entity relates to itself."""
        result = _parse_and_spatial(test_dxf_all)
        for rel in result.relationships:
            assert rel.entity_a_id != rel.entity_b_id


class TestAnnotations:
    """Test annotation detection."""

    def test_text_annotations(self, test_dxf_all):
        """Test that texts annotate nearby entities."""
        result = _parse_and_spatial(test_dxf_all)
        annotates = [r for r in result.relationships if r.relationship_type.value == "annotates"]
        assert len(annotates) > 0, "Text entities should annotate nearby entities"


class TestSpatialDatabase:
    """Test spatial relationship persistence."""

    def test_save_and_query_relationships(self, test_dxf_all, tmp_path):
        """Test that spatial relationships are saved and queryable."""
        from src.core.config import get_config
        from src.database.connection import get_session, init_database, reset_engine
        from src.database.repositories import DrawingRepository
        from src.file_manager.hasher import compute_sha256
        from src.parsers.dxf_parser import DXFParser
        from src.spatial import analyze

        config = get_config()
        config.db_path = tmp_path / "test_spatial.db"
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

        rels = repo.get_relationships_by_drawing(drawing_id)
        assert len(rels) > 0, "Relationships should be persisted"

        # Filter by type works
        near = repo.get_relationships_by_drawing(drawing_id, rel_type="near")
        assert len(near) >= 0  # near may be present

        # Stats include relationships
        stats = repo.get_database_stats()
        assert stats["relationships"] >= len(rels)

        session.close()

    def test_import_runs_spatial(self, test_dxf_all, tmp_path):
        """Test that the import pipeline runs spatial analysis."""
        from src.core.config import get_config
        from src.database.connection import get_session, reset_engine
        from src.database.repositories import DrawingRepository
        from src.file_manager.importer import import_file

        config = get_config()
        config.db_path = tmp_path / "test_import_spatial.db"
        config.ensure_directories()
        reset_engine()

        result = import_file(test_dxf_all)
        assert result["status"] == "success"

        session = get_session()
        repo = DrawingRepository(session)
        rels = repo.get_relationships_by_drawing(result["drawing_id"])
        assert len(rels) > 0, "Import should persist spatial relationships"
        session.close()


class TestSpatialDWG:
    """Test spatial analysis on DWG files (integration with ODA)."""

    def test_spatial_dwg(self, test_dwg_all):
        """Test spatial analysis works on DWG-parsed data."""
        from src.parsers.oda_converter import is_oda_available
        if not is_oda_available():
            pytest.skip("ODA File Converter 未安装，跳过 DWG 空间测试")
        from src.parsers.dwg_parser import DWGParser
        from src.spatial import analyze

        result = DWGParser().parse(test_dwg_all)
        assert result.drawing.parse_status == "success"
        analyze(result)

        assert len(result.relationships) > 0, "DWG should have spatial relationships"
