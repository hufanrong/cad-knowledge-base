"""Unit tests for Phase 2: unified file registry + multi-format detection.

Covers:
1. Multi-format file type detection (magic bytes, disguised files)
2. File registration: UUID file_id, SHA256 dedup, archive copy
3. Multi-source tracking (same content, different paths)
4. Metadata-only registration (missing original file)
5. Project creation / file relations / versions
"""

import pytest


@pytest.fixture(autouse=True)
def clean_files_table(tmp_path):
    """Redirect archive dir and clean files tables per test."""
    from src.core.config import get_config
    from src.database.connection import get_session, init_database, reset_engine
    from src.database.models import (
        FileModel, FileSourceModel, FileVersionModel,
        ProjectModel, FileRelationModel,
    )

    cfg = get_config()
    cfg.db_path = tmp_path / "test_registry.db"
    cfg.ensure_directories()
    reset_engine()
    init_database()

    session = get_session()
    for m in (FileRelationModel, ProjectModel, FileVersionModel,
              FileSourceModel, FileModel):
        session.query(m).delete()
    session.commit()
    session.close()
    yield


class TestFileTypeDetection:
    """Multi-format detection."""

    def test_detects_common_formats(self, tmp_path):
        """Test magic-byte detection for common formats."""
        from src.file_manager.version_detector import detect_file_type

        cases = [
            ("a.pdf", b"%PDF-1.7 fake", "pdf"),
            ("b.png", b"\x89PNG\r\n\x1a\nrest", "image"),
            ("c.jpg", b"\xff\xd8\xff\xe0fake", "image"),
            ("d.txt", b"hello world", "txt"),
            ("e.json", b'{"a":1}', "json"),
            ("f.xml", b"<root/>", "xml"),
            ("g.html", b"<html></html>", "html"),
            ("h.csv", b"a,b,c\n1,2,3", "csv"),
            ("i.rtf", b"{\\rtf1 content}", "rtf"),
        ]
        for name, content, expected in cases:
            p = tmp_path / name
            p.write_bytes(content)
            got = detect_file_type(p).value
            assert got == expected, f"{name}: expected {expected}, got {got}"

    def test_disguised_file_detected_by_content(self, tmp_path):
        """A .jpg that is actually a PDF must be detected as PDF."""
        from src.file_manager.version_detector import detect_file_type

        p = tmp_path / "fake.jpg"
        p.write_bytes(b"%PDF-1.4 disguised content")
        assert detect_file_type(p).value == "pdf"

    def test_dwg_magic_bytes(self, tmp_path):
        """DWG detection via AC header."""
        from src.file_manager.version_detector import detect_file_type

        p = tmp_path / "drawing.bin"  # no extension
        p.write_bytes(b"AC1032" + b"\x00" * 10)
        assert detect_file_type(p).value == "dwg"


class TestFileRegistration:
    """File registry core."""

    def test_register_and_archive_copy(self, tmp_path, test_dxf_all):
        """Register a file: UUID, archive copy created."""
        from src.core.file_registry import FileRegistry

        reg = FileRegistry(archive_root=tmp_path / "OriginalFiles")
        result = reg.register_file(test_dxf_all, parser="ezdxf",
                                   parse_status="success")
        assert result["status"] == "success"
        assert result["file_id"]
        assert result["sha256"]

        # Archive copy exists
        rec = reg.get_file(result["file_id"])
        assert rec.archive_path
        from pathlib import Path
        assert Path(rec.archive_path).exists()
        # Source recorded
        assert test_dxf_all.name in "".join(reg.list_sources(result["file_id"]))
        # Version recorded
        versions = reg.list_versions(result["file_id"])
        assert len(versions) == 1 and versions[0]["version_no"] == 1
        reg.close()

    def test_dedup_same_content(self, tmp_path, test_dxf_all):
        """Same content registered once; second path recorded as source."""
        from src.core.file_registry import FileRegistry

        copy = tmp_path / "copy.dxf"
        copy.write_bytes(open(test_dxf_all, "rb").read())

        reg = FileRegistry(archive_root=tmp_path / "OriginalFiles")
        r1 = reg.register_file(test_dxf_all)
        r2 = reg.register_file(copy)

        assert r2["status"] == "duplicate"
        assert r2["file_id"] == r1["file_id"]
        # Both sources tracked
        sources = reg.list_sources(r1["file_id"])
        assert len(sources) == 2
        # Only one archive copy
        from pathlib import Path
        arc = Path(r1["file_id"] and reg.get_file(r1["file_id"]).archive_path)
        assert arc.exists()
        reg.close()

    def test_metadata_only_when_original_missing(self, tmp_path):
        """Missing original -> metadata-only registration, no crash."""
        from src.core.file_registry import FileRegistry

        reg = FileRegistry(archive_root=tmp_path / "OriginalFiles")
        fid = reg.register_metadata_only(
            original_name="lost.dwg",
            original_path="C:/nonexistent/lost.dwg",
            sha256="deadbeef" * 8,
            file_type="dwg",
            parse_status="pending",
        )
        assert fid
        rec = reg.get_file(fid)
        assert rec.archive_path == ""
        assert rec.parse_status == "pending"
        reg.close()

    def test_update_parse_status_and_link_drawing(self, tmp_path, test_dxf_all):
        """Parse status update + drawing link."""
        from src.core.file_registry import FileRegistry

        reg = FileRegistry(archive_root=tmp_path / "OriginalFiles")
        r = reg.register_file(test_dxf_all, parse_status="pending")
        reg.update_parse_status(r["file_id"], "success", parser="ezdxf")
        reg.link_drawing(r["file_id"], "drawing-123")

        rec = reg.get_file(r["file_id"])
        assert rec.parse_status == "success"
        assert rec.drawing_id == "drawing-123"
        reg.close()


class TestProjectAndRelations:
    """Projects, relations, search."""

    def test_project_create_and_assign(self, tmp_path, test_dxf_all):
        """Create project with confidence, assign to file."""
        from src.core.file_registry import FileRegistry

        reg = FileRegistry(archive_root=tmp_path / "OriginalFiles")
        proj = reg.get_or_create_project("205冷却窑", confidence=0.92,
                                         source="filename")
        assert proj.name == "205冷却窑"
        assert proj.confidence == 0.92

        r = reg.register_file(test_dxf_all)
        reg.assign_project(r["file_id"], proj.project_id)
        rec = reg.get_file(r["file_id"])
        assert rec.project_id == proj.project_id

        # Re-fetch project (dedup by name)
        proj2 = reg.get_or_create_project("205冷却窑")
        assert proj2.project_id == proj.project_id
        reg.close()

    def test_file_relations(self, tmp_path, test_dxf_all):
        """Add and list relations."""
        from src.core.file_registry import FileRegistry

        reg = FileRegistry(archive_root=tmp_path / "OriginalFiles")
        r1 = reg.register_file(test_dxf_all)
        r2 = reg.register_file(test_dxf_all)  # duplicate

        reg.add_relation(r1["file_id"], r2["file_id"],
                         "same_content", source="hash")
        rels = reg.list_relations(r1["file_id"])
        assert len(rels) >= 1
        assert rels[0]["relation_type"] == "same_content"
        reg.close()

    def test_search_files_by_name(self, tmp_path, test_dxf_all):
        """Search by filename keyword."""
        from src.core.file_registry import FileRegistry

        reg = FileRegistry(archive_root=tmp_path / "OriginalFiles")
        reg.register_file(test_dxf_all)
        hits = reg.search_files("test_all")
        assert len(hits) >= 1
        reg.close()
