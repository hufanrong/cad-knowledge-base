"""Unit tests for Phase 6: document vectorization + unified Agent API.

Covers:
1. Document chunking
2. Document vector index (index + query)
3. Agent API surface: search_documents/excel, get_file/original/parsed
4. Cross-format QA includes document context
5. REST endpoints registered
"""

import pytest


@pytest.fixture(autouse=True)
def kb6(tmp_path):
    """Isolated KB with vector dir."""
    from src.core.config import get_config
    from src.database.connection import get_session, init_database, reset_engine
    from src.database.models import (
        DocumentContentModel, FileModel, FileRelationModel, FileSourceModel,
        FileVersionModel, ProjectModel,
    )

    cfg = get_config()
    cfg.db_path = tmp_path / "p6.db"
    cfg.raw_dir = tmp_path / "OriginalFiles"
    cfg.parsed_dir = tmp_path / "ParsedData"
    cfg.embeddings_dir = tmp_path / "VectorDB"
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
def imported(kb6):
    """Import docs so vector index has entries."""
    from src.file_manager.importer import import_file

    r1 = import_file("tests/fixtures/docs/205冷却窑安装方案.docx")
    r2 = import_file("tests/fixtures/docs/设备清单.xlsx")
    r3 = import_file("tests/fixtures/docs/材料表.csv")
    return {"word": r1, "excel": r2, "csv": r3}


class TestDocumentChunking:
    def test_chunk_split(self):
        from src.core.document_rag import chunk_document_text

        text = "\n".join(f"第{i}行 冷却窑参数说明内容" for i in range(50))
        chunks = chunk_document_text(text, "file-1", "word", "测试文档")
        assert len(chunks) >= 2
        assert all(c.source_type == "document" for c in chunks)
        assert all(c.drawing_id == "file-1" for c in chunks)
        assert all(c.metadata["source_type"] == "word" for c in chunks)

    def test_empty_content(self):
        from src.core.document_rag import chunk_document_text

        assert chunk_document_text("", "f", "word") == []


class TestDocumentVector:
    def test_index_and_query(self, imported):
        """Document content is indexed and retrievable by semantics."""
        from src.core.document_rag import query_documents
        from src.index.vector_index import VectorIndex

        vi = VectorIndex()
        assert vi.count() >= 3  # one chunk per small doc

        results = query_documents("Q355B")
        assert any("Q355B" in r["content"] for r in results)

    def test_query_where_filter(self, imported):
        """Only document chunks returned (not CAD)."""
        from src.core.document_rag import query_documents

        results = query_documents("设备")
        # Top-level source_type must be the document marker; metadata
        # carries the real type (word/excel/csv...)
        assert all(
            r["source_type"] == "document"
            for r in results
        )


class TestAgentAPI:
    def test_search_documents(self, imported):
        from src.core.agent_api import search_documents

        results = search_documents("Q355B")
        assert len(results) >= 1
        assert all(r["source_type"] != "cad" for r in results)

    def test_search_excel(self, imported):
        from src.core.agent_api import search_excel

        results = search_excel("Q355B")
        assert len(results) >= 1
        assert all(r["source_type"] == "excel" for r in results)

    def test_get_file_and_original(self, imported):
        from src.core.agent_api import get_file, get_original_file

        fid = imported["excel"]["file_id"]
        rec = get_file(fid)
        assert rec and rec["file_name"].endswith(".xlsx")

        o = get_original_file(fid)
        assert o["archive_path"], "archive copy must exist"
        assert o["file_id"] == fid

    def test_get_parsed_data(self, imported):
        from src.core.agent_api import get_parsed_data

        fid = imported["word"]["file_id"]
        data = get_parsed_data(fid)
        assert data["source_type"] == "word"
        assert "冷却窑" in data["content"]
        assert data["md_path"]

    def test_search_projects(self, imported):
        from src.core.agent_api import search_projects

        projects = search_projects()
        assert any(p["name"] == "205冷却窑" for p in projects)

    def test_unknown_file_returns_error(self):
        from src.core.agent_api import get_original_file

        r = get_original_file("nonexistent-id")
        assert "error" in r


class TestCrossFormatQA:
    def test_qa_includes_documents(self, imported):
        """Evidence-mode QA context must include document content."""
        from src.qa.qa_service import ask_question

        ans = ask_question("冷却窑安装要求", top_k=6)
        texts = " ".join(i.content for i in ans.context_items)
        assert "205冷却窑安装方案" in texts or "本方案适用于" in texts


class TestRESTEndpoints:
    def test_endpoints_registered(self):
        from src.api.app import app

        routes = {r.path for r in app.routes}
        for ep in ("/api/files", "/api/search-all", "/api/projects",
                   "/api/documents/{file_id}/content"):
            assert ep in routes, ep
