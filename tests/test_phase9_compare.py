"""Unit tests for Phase 9: Drawing comparison.

Covers:
1. Entity-level diff (added / removed / modified)
2. Text diff
3. Title-block field diff
4. Comparison report summary
5. Identical drawings produce no changes
"""

import pytest


@pytest.fixture
def modified_dxf(test_dxf_all, tmp_path):
    """Create a modified copy of the test DXF for comparison."""
    import ezdxf

    out = tmp_path / "test_modified.dxf"
    doc = ezdxf.readfile(test_dxf_all)
    msp = doc.modelspace()

    # Change title block 图号
    for t in msp.query("TEXT"):
        if t.dxf.text == "2024-001":
            t.dxf.text = "2024-002"

    # Add a circle
    msp.add_circle((800, 400), 30, dxfattribs={"layer": "EQUIPMENT"})

    # Modify first LINE's endpoint
    lines = list(msp.query("LINE"))
    if lines:
        lines[0].dxf.end = (1000, 200)

    doc.saveas(str(out))
    return out


def _parse(dxf_path):
    """Parse a DXF and run semantic analysis."""
    from src.parsers.dxf_parser import DXFParser
    from src.semantic import analyze

    result = DXFParser().parse(dxf_path)
    assert result.drawing.parse_status == "success"
    analyze(result)
    return result


class TestCompare:
    """Test drawing comparison."""

    def test_compare_identical(self, test_dxf_all):
        """Test that identical drawings produce no changes."""
        from src.compare import compare_drawings

        a = _parse(test_dxf_all)
        b = _parse(test_dxf_all)
        report = compare_drawings(a, b, "a", "b")
        assert report.total_changes == 0, f"Identical should have 0 changes, got {report.total_changes}"

    def test_compare_modified(self, test_dxf_all, modified_dxf):
        """Test that modified drawing is detected."""
        from src.compare import compare_drawings

        a = _parse(test_dxf_all)
        b = _parse(modified_dxf)
        report = compare_drawings(a, b, "original", "modified")

        s = report.summary
        assert s["entities"]["added"] >= 1   # circle added
        assert s["texts"]["modified"] >= 1   # 图号 text changed
        assert s["title_fields"] >= 1        # 图号 field changed
        assert report.total_changes > 0

    def test_entity_modified_detected(self, test_dxf_all, modified_dxf):
        """Test that modified entity is detected."""
        from src.compare import compare_drawings

        a = _parse(test_dxf_all)
        b = _parse(modified_dxf)
        report = compare_drawings(a, b, "a", "b")
        assert len(report.entity_modified) >= 1

    def test_title_field_change(self, test_dxf_all, modified_dxf):
        """Test title-block field change detection."""
        from src.compare import compare_drawings

        a = _parse(test_dxf_all)
        b = _parse(modified_dxf)
        report = compare_drawings(a, b, "a", "b")

        assert len(report.title_field_changes) >= 1
        change = report.title_field_changes[0]
        assert change.detail == "图号"
        assert change.old_content == "2024-001"
        assert change.new_content == "2024-002"

    def test_text_modified_detected(self, test_dxf_all, modified_dxf):
        """Test text change detection."""
        from src.compare import compare_drawings

        a = _parse(test_dxf_all)
        b = _parse(modified_dxf)
        report = compare_drawings(a, b, "a", "b")

        assert len(report.texts_modified) >= 1
        assert any(t.old_content == "2024-001" and t.new_content == "2024-002"
                   for t in report.texts_modified)

    def test_report_summary_structure(self, test_dxf_all, modified_dxf):
        """Test the report summary structure."""
        from src.compare import compare_drawings

        a = _parse(test_dxf_all)
        b = _parse(modified_dxf)
        report = compare_drawings(a, b, "a", "b")

        s = report.summary
        assert "entities" in s
        assert "texts" in s
        assert "dimensions" in s
        assert "equipment" in s
        assert "title_fields" in s
        # total_changes equals sum
        total = (
            sum(s["entities"].values())
            + sum(s["texts"].values())
            + sum(s["dimensions"].values())
            + sum(s["equipment"].values())
            + s["title_fields"]
        )
        assert total == report.total_changes


class TestCompareAPI:
    """Test comparison REST endpoint."""

    def test_api_compare(self, test_dxf_all, modified_dxf):
        """Test POST /api/compare."""
        from fastapi.testclient import TestClient
        from src.api.app import app

        with TestClient(app) as client:
            resp = client.post("/api/compare", json={
                "file_a": str(test_dxf_all),
                "file_b": str(modified_dxf),
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_changes"] > 0
            assert data["summary"]["entities"]["added"] >= 1
            assert len(data["entity_added"]) >= 1
            assert len(data["title_field_changes"]) >= 1

    def test_api_compare_missing_file(self):
        """Test 404 for missing file."""
        from fastapi.testclient import TestClient
        from src.api.app import app

        with TestClient(app) as client:
            resp = client.post("/api/compare", json={
                "file_a": "C:/nonexistent/a.dxf",
                "file_b": "C:/nonexistent/b.dxf",
            })
            assert resp.status_code == 404
