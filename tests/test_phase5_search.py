"""Unit tests for Phase 5: Search system.

Covers:
1. Full-text search (FTS5) on texts / attributes / drawings
2. Structured search (equipment / title fields / dimensions / entity type)
3. Spatial search (region query / near entity)
4. Provenance on every result
"""

import pytest


@pytest.fixture
def imported_db(test_dxf_all, tmp_path):
    """Import a test drawing into a temp DB and return drawing_id."""
    from src.core.config import get_config
    from src.database.connection import reset_engine
    from src.file_manager.importer import import_file

    config = get_config()
    config.db_path = tmp_path / "test_search.db"
    config.ensure_directories()
    reset_engine()

    result = import_file(test_dxf_all)
    assert result["status"] == "success"
    return result["drawing_id"]


class TestFulltextSearch:
    """Test FTS5 full-text search."""

    def test_search_text(self, imported_db):
        """Test searching text content."""
        from src.index.search_service import SearchService

        svc = SearchService()
        results = svc.search("酸化窑", search_type="text")
        svc.close()

        assert len(results) > 0
        text_results = [r for r in results if r.result_type == "text"]
        assert any("酸化窑" in r.content for r in text_results)

    def test_search_attribute(self, imported_db):
        """Test searching block attributes."""
        from src.index.search_service import SearchService

        svc = SearchService()
        results = svc.search("球磨机", search_type="attribute")
        svc.close()

        assert len(results) > 0
        assert all(r.result_type == "attribute" for r in results)

    def test_search_drawing(self, imported_db):
        """Test searching drawings by filename."""
        from src.index.search_service import SearchService

        svc = SearchService()
        results = svc.search("test_all", search_type="drawing")
        svc.close()

        assert len(results) > 0
        assert all(r.result_type == "drawing" for r in results)

    def test_search_result_provenance(self, imported_db):
        """Test that results carry provenance."""
        from src.index.search_service import SearchService

        svc = SearchService()
        results = svc.search("酸化窑", search_type="text")
        svc.close()

        for r in results:
            assert r.drawing_id, "drawing_id required"
            assert r.entity_id, "entity_id required"
            assert r.content, "content required"


class TestStructuredSearch:
    """Test structured search."""

    def test_search_equipment(self, imported_db):
        """Test equipment search."""
        from src.index.search_service import SearchService

        svc = SearchService()
        results = svc.search("MILL", search_type="equipment")
        svc.close()

        assert len(results) >= 2
        nos = [r.extra.get("equipment_no") for r in results]
        assert "MILL-001" in nos
        assert "MILL-002" in nos

    def test_search_equipment_by_name(self, imported_db):
        """Test equipment search by Chinese name."""
        from src.index.search_service import SearchService

        svc = SearchService()
        results = svc.search("球磨机", search_type="equipment")
        svc.close()

        assert len(results) >= 1
        assert results[0].result_type == "equipment"

    def test_search_title_field(self, imported_db):
        """Test title block field search."""
        from src.index.search_service import SearchService

        svc = SearchService()
        results = svc.search("2024-001", search_type="title_field")
        svc.close()

        assert len(results) >= 1
        assert results[0].result_type == "title_field"
        assert results[0].extra.get("key") == "图号"

    def test_search_dimension(self, imported_db):
        """Test dimension search."""
        from src.index.search_service import SearchService

        svc = SearchService()
        results = svc.search("", search_type="dimension", limit=10)
        svc.close()

        # All dimensions returned
        assert len(results) > 0
        assert all(r.result_type == "dimension" for r in results)

    def test_search_by_entity_type(self, imported_db):
        """Test entity-type structured search."""
        from src.index.search_service import SearchService

        svc = SearchService()
        results = svc.search(
            "", search_type="entity", entity_type="CIRCLE", limit=10
        )
        svc.close()

        assert len(results) > 0
        assert all(r.extra.get("entity_type") == "CIRCLE" for r in results)


class TestSpatialSearch:
    """Test spatial search."""

    def test_search_in_region(self, imported_db):
        """Test region search returns entities inside the region."""
        from src.index.search_service import search_in_region

        results = search_in_region(
            min_x=0, min_y=0, max_x=1500, max_y=1500,
            entity_types=["TEXT"],
            limit=100,
        )
        assert len(results) > 0
        for r in results:
            assert r.extra.get("in_region") is True
            assert r.result_type == "entity"
            # Provenance
            assert r.drawing_id

    def test_search_in_region_excludes_outside(self, imported_db):
        """Test that entities outside the region are excluded."""
        from src.index.search_service import search_in_region

        # Narrow region that contains only the frame (0,0)-(1000,500)
        results = search_in_region(
            min_x=100, min_y=100, max_x=900, max_y=400,
            limit=100,
        )
        for r in results:
            bbox = r.extra.get("bbox")
            if bbox:
                assert bbox[0] >= 100 and bbox[2] <= 900, "Entity outside region"
                assert bbox[1] >= 100 and bbox[3] <= 400, "Entity outside region"

    def test_near_entity(self, imported_db):
        """Test searching entities near a given entity."""
        from src.database.connection import get_session
        from src.database.models import EntityModel
        from src.index.search_service import SearchService

        session = get_session()
        circle = (
            session.query(EntityModel)
            .filter(EntityModel.entity_type == "CIRCLE")
            .first()
        )
        session.close()
        assert circle, "Need a CIRCLE to test near search"

        svc = SearchService()
        results = svc.search_near_entity(circle.entity_id)
        svc.close()

        # CIRCLE at (200,250) and (500,250) — may have near relations
        assert isinstance(results, list)


class TestUnifiedSearch:
    """Test the unified search entry."""

    def test_search_all_types(self, imported_db):
        """Test unified 'all' search returns mixed types."""
        from src.index.search_service import SearchService

        svc = SearchService()
        results = svc.search("酸化窑", search_type="all", limit=50)
        svc.close()

        assert len(results) > 0
        types = {r.result_type for r in results}
        # Should include at least text + equipment + title_field
        assert "text" in types
        assert "equipment" in types

    def test_search_layer_filter(self, imported_db):
        """Test layer filter narrows results."""
        from src.index.search_service import SearchService

        svc = SearchService()
        results = svc.search("", search_type="text", layer="标注", limit=50)
        svc.close()

        assert len(results) > 0
        for r in results:
            assert r.layer == "标注"

    def test_search_dedup(self, imported_db):
        """Test that unified search deduplicates."""
        from src.index.search_service import SearchService

        svc = SearchService()
        results = svc.search("酸化窑", search_type="all", limit=50)
        svc.close()

        keys = {(r.result_type, r.drawing_id, r.entity_id, r.content) for r in results}
        assert len(keys) == len(results), "Results should be deduplicated"
