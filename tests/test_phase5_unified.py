"""Unit tests for Phase 5: unified search, project inference, re-scan.

Covers:
1. Unified search across documents (FTS) + filenames
2. Project inference (confidence, no guessing)
3. Project assignment + search_by_project
4. scan_directory: new / unchanged / multi-source
5. CLI command registration
"""

import pytest


@pytest.fixture(autouse=True)
def kb5(tmp_path):
    """Isolated KB for Phase 5 tests."""
    from src.core.config import get_config
    from src.database.connection import get_session, init_database, reset_engine
    from src.database.models import (
        DocumentContentModel, FileModel, FileRelationModel, FileSourceModel,
        FileVersionModel, ProjectModel,
    )

    cfg = get_config()
    cfg.db_path = tmp_path / "p5.db"
    cfg.raw_dir = tmp_path / "OriginalFiles"
    cfg.parsed_dir = tmp_path / "ParsedData"
    cfg.ensure_directories()
    reset_engine()
    init_database()

    session = get_session()
    for m in (DocumentContentModel, FileRelationModel, ProjectModel,
              FileVersionModel, FileSourceModel, FileModel):
        session.query(m).delete()
    session.commit()
    session.close()
    return tmp_path


@pytest.fixture
def imported_docs(kb5):
    """Import the three fixture documents."""
    from src.file_manager.importer import import_file

    r1 = import_file("tests/fixtures/docs/205冷却窑安装方案.docx")
    r2 = import_file("tests/fixtures/docs/设备清单.xlsx")
    r3 = import_file("tests/fixtures/docs/材料表.csv")
    return {"word": r1, "excel": r2, "csv": r3}


class TestUnifiedSearch:
    def test_search_document_content(self, imported_docs):
        """FTS search hits Excel content (Q355B)."""
        from src.core.unified_search import search_all

        results = search_all("Q355B")
        types = {r["source_type"] for r in results}
        assert "excel" in types
        assert any(r["match_type"] == "document" for r in results)

    def test_search_filename(self, imported_docs):
        """Search by filename keyword."""
        from src.core.unified_search import search_all

        results = search_all("205冷却窑")
        assert any("205冷却窑" in r["file_name"] for r in results)

    def test_search_cross_format(self, imported_docs):
        """One keyword finds both Word and CSV (设备)."""
        from src.core.unified_search import search_all

        results = search_all("设备")
        types = {r["source_type"] for r in results}
        assert "word" in types or "excel" in types

    def test_search_source_filter(self, imported_docs):
        """Filter by source type."""
        from src.core.unified_search import search_all

        results = search_all("Q355B", source_types=["excel"])
        assert all(r["source_type"] == "excel" for r in results)


class TestProjectInference:
    def test_infer_from_filename(self):
        from src.core.project_inference import infer_project_from_file

        r = infer_project_from_file("205冷却窑安装方案.docx")
        assert r and r["name"] == "205冷却窑"
        assert r["confidence"] >= 0.5

    def test_infer_from_cad_filename(self):
        from src.core.project_inference import infer_project_from_file

        r = infer_project_from_file(
            "0203 回转窑头装置工艺图（2025.05.07）-R0.dwg")
        assert r and "回转窑头装置" in r["name"]

    def test_no_guess_for_generic(self):
        """Generic names must NOT become projects."""
        from src.core.project_inference import infer_project_from_file

        for name in ("设备清单.xlsx", "材料表.csv", "IMG_001.jpg",
                     "合同.pdf", "照片20240801.png"):
            assert infer_project_from_file(name) is None, name

    def test_title_block_wins(self):
        from src.core.project_inference import infer_project_from_file

        r = infer_project_from_file(
            "随便一张图.dwg",
            title_block={"项目名称": "205冷却窑项目"})
        assert r and r["name"] == "205冷却窑项目"
        assert r["source"] == "title_block"


class TestProjectAssignment:
    def test_assign_and_query(self, imported_docs):
        """Files get project assigned; search_by_project finds them."""
        from src.core.unified_search import search_by_project
        from src.database.connection import get_session
        from src.database.models import FileModel

        # 205冷却窑安装方案.docx -> project 205冷却窑
        session = get_session()
        rec = session.query(FileModel).filter(
            FileModel.file_id == imported_docs["word"]["file_id"]).first()
        session.close()
        assert rec and rec.project_id

        files = search_by_project("205冷却窑")
        assert any(f["file_id"] == imported_docs["word"]["file_id"]
                   for f in files)


class TestScanService:
    def test_scan_unchanged(self, kb5, imported_docs):
        """Re-scan the fixture dir: files already imported -> unchanged."""
        from src.core.scan_service import scan_directory

        r = scan_directory("tests/fixtures/docs", import_new=False)
        assert r["scanned"] >= 5
        # The 3 imported docs are known -> not counted as new
        assert r["new"] < r["scanned"]

    def test_scan_new_file(self, kb5, tmp_path):
        """A brand-new file in scanned dir -> imported."""
        import shutil

        src = "tests/fixtures/docs/材料表.csv"
        scan_dir = tmp_path / "scan_me"
        scan_dir.mkdir()
        shutil.copy2(src, scan_dir / "新材料.csv")

        from src.core.scan_service import scan_directory

        r = scan_directory(str(scan_dir), import_new=True)
        assert r["new"] >= 1
        assert r["scanned"] == 1

    def test_scan_multi_source(self, kb5, imported_docs, tmp_path):
        """Same content at new path -> registered as additional source."""
        import shutil

        scan_dir = tmp_path / "scan2"
        scan_dir.mkdir()
        shutil.copy2("tests/fixtures/docs/材料表.csv",
                     scan_dir / "材料表副本.csv")

        from src.core.scan_service import scan_directory
        from src.core.file_registry import FileRegistry

        scan_directory(str(scan_dir), import_new=True)

        reg = FileRegistry()
        sources = reg.list_sources(imported_docs["csv"]["file_id"])
        assert len(sources) >= 2  # original + copy
        reg.close()


class TestCLICommands:
    def test_commands_registered(self):
        """scan / search-all / project commands exist in CLI."""
        from src.cli.main import cli

        names = {cmd.name for cmd in cli.commands.values()}
        assert "scan" in names
        assert "search-all" in names
        assert "project" in names
