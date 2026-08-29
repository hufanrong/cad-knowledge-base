"""Unit tests for Phase 7: AI QA + provenance + REST API.

Covers:
1. Context builder (provenance-carrying context)
2. QA service (evidence mode without LLM; llm mode with mocked client)
3. LLM client (availability, error handling)
4. REST API endpoints (TestClient)
"""

import pytest

# Force n-gram embedder for offline tests
@pytest.fixture(autouse=True)
def use_ngram_embedder(monkeypatch):
    from src.index import vector_index
    monkeypatch.setattr(vector_index, "_embedder", None)
    monkeypatch.setattr(vector_index, "_embedder_backend", "ngram")


@pytest.fixture
def imported_db(test_dxf_all, tmp_path):
    """Import a test drawing into a temp DB and return drawing_id."""
    from src.core.config import get_config
    from src.database.connection import reset_engine
    from src.file_manager.importer import import_file

    config = get_config()
    config.db_path = tmp_path / "test_qa.db"
    config.ensure_directories()
    reset_engine()

    result = import_file(test_dxf_all)
    assert result["status"] == "success"
    return result["drawing_id"]


class TestContextBuilder:
    """Test context building with provenance."""

    def test_build_context_traceable(self):
        """Test that results with provenance are marked traceable."""
        from src.rag.context_builder import ContextBuilder

        results = [
            {
                "content": "酸化窑 φ4500×45000",
                "source_type": "text",
                "drawing_id": "d1",
                "handle": "A1",
                "layer": "标注",
                "score": 0.8,
                "metadata": {"file_name": "test.dxf"},
            },
            {
                "content": "无法追溯的内容",
                "source_type": "text",
                "drawing_id": "",
                "handle": "",
                "layer": "",
                "score": 0.5,
                "metadata": {},
            },
        ]
        ctx = ContextBuilder().build(results, "酸化窑")
        assert len(ctx.items) == 2
        assert ctx.traceable == 1
        assert ctx.untraceable == 1

        # First item has provenance
        first = ctx.items[0]
        assert first.source.drawing_id == "d1"
        assert first.source.file == "test.dxf"
        assert first.source.entity_handle == "A1"
        assert first.source.layer == "标注"

    def test_to_llm_text(self):
        """Test rendering context for the LLM prompt."""
        from src.rag.context_builder import ContextBuilder

        results = [
            {
                "content": "φ4500×45000",
                "source_type": "text",
                "drawing_id": "d1",
                "handle": "A1",
                "layer": "标注",
                "score": 0.8,
                "metadata": {"file_name": "酸化窑.dwg"},
            },
            {
                "content": "孤儿数据",
                "source_type": "text",
                "drawing_id": "",
                "handle": "",
                "layer": "",
                "score": 0.1,
                "metadata": {},
            },
        ]
        ctx = ContextBuilder().build(results)
        text = ctx.to_llm_text()
        assert "酸化窑.dwg" in text
        assert "图层: 标注" in text
        assert "无法追溯" in text


class TestQAService:
    """Test QA service orchestration."""

    def test_evidence_mode_without_llm(self, imported_db):
        """Test that QA works in evidence mode without an LLM."""
        from src.qa import QAService

        # No llm_client => evidence mode
        qa = QAService(llm_client=None)
        ans = qa.ask("酸化窑直径", top_k=5)

        assert ans.mode == "evidence"
        assert not ans.llm_available
        assert ans.answer == ""
        assert len(ans.context_items) > 0
        assert ans.traceable_count >= 1

    def test_llm_mode_with_mock(self, imported_db):
        """Test that QA uses the LLM when available."""
        from src.qa import QAService

        class MockLLM:
            available = True
            model = "mock-model"

            def system_prompt(self, instructions):
                return {"role": "system", "content": instructions}

            def chat(self, messages, **kwargs):
                # Verify prompt contains context with provenance
                user = messages[-1]["content"]
                assert "酸化窑" in user
                return "酸化窑直径为 φ4500mm，来源可追溯。"

        qa = QAService(llm_client=MockLLM())
        ans = qa.ask("酸化窑直径", top_k=5)

        assert ans.mode == "llm"
        assert ans.llm_available
        assert ans.llm_model == "mock-model"
        assert "φ4500" in ans.answer
        assert len(ans.context_items) > 0

    def test_llm_failure_falls_back(self, imported_db):
        """Test that LLM failure falls back to evidence mode."""
        from src.qa import QAService

        class FailingLLM:
            available = True
            model = "failing"

            def system_prompt(self, instructions):
                return {"role": "system", "content": instructions}

            def chat(self, messages, **kwargs):
                raise RuntimeError("network down")

        qa = QAService(llm_client=FailingLLM())
        ans = qa.ask("酸化窑", top_k=3)

        assert ans.mode == "evidence"
        assert ans.llm_error
        assert len(ans.context_items) > 0


class TestLLMClient:
    """Test LLM client behavior."""

    def test_unavailable_without_key(self, tmp_path, monkeypatch):
        """Test that client reports unavailable without api_key."""
        from src.core.config import get_config
        from src.llm.client import LLMClient

        # Force empty api key
        monkeypatch.setenv("CADKB_LLM_API_KEY", "")
        cfg = get_config()
        cfg.llm_api_key = ""

        client = LLMClient()
        assert not client.available

    def test_available_with_key(self, tmp_path, monkeypatch):
        """Test that client reports available with api_key."""
        from src.core.config import get_config
        from src.llm.client import LLMClient

        monkeypatch.setenv("CADKB_LLM_API_KEY", "test-key")
        cfg = get_config()
        cfg.llm_api_key = "test-key"

        client = LLMClient()
        assert client.available
        assert "test-key" in client.api_key

    def test_chat_requires_key(self):
        """Test that chat raises LLMError when no key."""
        from src.core.config import get_config
        from src.llm.client import LLMClient, LLMError

        cfg = get_config()
        cfg.llm_api_key = ""

        client = LLMClient()
        with pytest.raises(LLMError):
            client.chat([{"role": "user", "content": "hi"}])


class TestRESTAPI:
    """Test REST API endpoints."""

    def test_status_endpoint(self, imported_db):
        """Test /api/status."""
        from fastapi.testclient import TestClient
        from src.api.app import app

        with TestClient(app) as client:
            resp = client.get("/api/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert "drawings" in data

    def test_drawings_endpoint(self, imported_db):
        """Test /api/drawings."""
        from fastapi.testclient import TestClient
        from src.api.app import app

        with TestClient(app) as client:
            resp = client.get("/api/drawings")
            assert resp.status_code == 200
            rows = resp.json()
            assert len(rows) >= 1

    def test_search_endpoint(self, imported_db):
        """Test /api/search."""
        from fastapi.testclient import TestClient
        from src.api.app import app

        with TestClient(app) as client:
            resp = client.get("/api/search", params={"q": "酸化窑"})
            assert resp.status_code == 200
            results = resp.json()
            assert len(results) > 0
            # Provenance in results
            assert all(r["drawing_id"] for r in results)

    def test_query_endpoint_evidence(self, imported_db):
        """Test POST /api/query in evidence mode (no LLM)."""
        from fastapi.testclient import TestClient
        from src.api.app import app

        with TestClient(app) as client:
            resp = client.post("/api/query", json={"query": "酸化窑直径", "top_k": 5})
            assert resp.status_code == 200
            data = resp.json()
            assert data["mode"] in ("llm", "evidence")
            assert len(data["context"]) > 0
            # Provenance attached to each context item
            for item in data["context"]:
                assert "source" in item
                assert "content" in item
