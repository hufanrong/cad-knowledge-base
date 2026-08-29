"""Unit tests for Phase 6: RAG system.

Covers:
1. Chunker (分块 with provenance)
2. Vector index (index/query, memory fallback + chroma if available)
3. Hybrid search (FTS + vector + structured merged)
4. Reranker

NOTE: These tests force the n-gram fallback embedder so they run
offline without downloading models. The vector_index module caches
the embedder globally, so we monkeypatch to the fallback.
"""

import pytest


@pytest.fixture(autouse=True)
def use_ngram_embedder(monkeypatch):
    """Force the deterministic n-gram embedder for all RAG tests."""
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
    config.db_path = tmp_path / "test_rag.db"
    config.ensure_directories()
    reset_engine()

    result = import_file(test_dxf_all)
    assert result["status"] == "success"
    return result["drawing_id"]


@pytest.fixture
def chunks(test_dxf_all):
    """Parse a DXF and produce chunks."""
    from src.chunker import chunk_result
    from src.parsers.dxf_parser import DXFParser
    from src.semantic import analyze

    result = DXFParser().parse(test_dxf_all)
    result.drawing.file_name = test_dxf_all.name
    analyze(result)
    return chunk_result(result)


class TestChunker:
    """Test document chunking."""

    def test_chunks_generated(self, chunks):
        """Test that chunks are generated from all sources."""
        assert len(chunks) > 0

        source_types = {c.source_type for c in chunks}
        assert "text" in source_types
        assert "attribute" in source_types
        assert "title_field" in source_types
        assert "equipment" in source_types

    def test_chunk_provenance(self, chunks):
        """Test that chunks carry provenance."""
        for c in chunks:
            assert c.content, "Chunk must have content"
            assert c.drawing_id, "Chunk must have drawing_id"
            assert c.source_type, "Chunk must have source_type"

    def test_chunk_content(self, chunks):
        """Test that specific content survives chunking."""
        all_content = " ".join(c.content for c in chunks)
        assert "酸化窑" in all_content
        assert "球磨机" in all_content or "MILL-001" in all_content
        assert "2024-001" in all_content  # title block 图号


class TestVectorIndex:
    """Test vector index operations (with n-gram fallback)."""

    def test_index_and_query(self, chunks, tmp_path):
        """Test indexing chunks and querying them back."""
        from src.index.vector_index import VectorIndex

        vi = VectorIndex(persist_dir=tmp_path / "vectordb")
        n = vi.index_chunks(chunks)
        assert n == len(chunks)
        assert vi.count() == len(chunks)

        # Query with content that exists
        results = vi.query("酸化窑", top_k=5)
        assert len(results) > 0

        # At least one result should relate to 酸化窑
        contents = " | ".join(r["content"] for r in results)
        assert "酸化窑" in contents

    def test_query_provenance(self, chunks, tmp_path):
        """Test that vector results carry provenance."""
        from src.index.vector_index import VectorIndex

        vi = VectorIndex(persist_dir=tmp_path / "vectordb")
        vi.index_chunks(chunks)

        results = vi.query("球磨机", top_k=3)
        for r in results:
            assert r["drawing_id"], "Missing drawing_id in vector result"
            assert r["content"], "Missing content in vector result"
            assert r["source_type"], "Missing source_type"

    def test_delete_drawing(self, chunks, tmp_path):
        """Test deleting a drawing from the index."""
        from src.index.vector_index import VectorIndex

        vi = VectorIndex(persist_dir=tmp_path / "vectordb")
        vi.index_chunks(chunks)
        drawing_id = chunks[0].drawing_id

        removed = vi.delete_drawing(drawing_id)
        assert removed == len(chunks)
        assert vi.count() == 0


class TestHybridSearch:
    """Test hybrid retrieval."""

    def test_hybrid_search_works(self, imported_db, tmp_path):
        """Test hybrid search returns results."""
        from src.chunker import chunk_result
        from src.database.connection import get_session
        from src.database.repositories import DrawingRepository
        from src.index.vector_index import VectorIndex
        from src.rag.hybrid_search import hybrid_search

        # Build chunks from DB
        session = get_session()
        repo = DrawingRepository(session)
        # Reuse existing drawing_id
        drawing_id = imported_db
        texts = repo.get_texts_by_drawing(drawing_id, limit=1000)
        session.close()

        assert len(texts) > 0

        # Index via vector index directly (from persisted texts)
        vi = VectorIndex(persist_dir=tmp_path / "vectordb")
        from src.chunker.chunker import DocumentChunk

        chunks = [
            DocumentChunk(
                drawing_id=drawing_id,
                source_type="text",
                content=t["text_content"],
                entity_id=t.get("entity_id", ""),
                handle=t.get("handle", ""),
                layer=t.get("layer", ""),
            )
            for t in texts
            if t.get("text_content")
        ]
        vi.index_chunks(chunks)

        results = hybrid_search("酸化窑", top_k=5, vector_index=vi)
        assert len(results) > 0

        # Results carry provenance + scores
        for r in results:
            assert "content" in r
            assert "source_type" in r
            assert "drawing_id" in r
            assert "score" in r


class TestReranker:
    """Test re-ranking."""

    def test_rerank_orders_results(self):
        """Test that reranker sorts by relevance."""
        from src.rag.reranker import rerank

        results = [
            {"content": "酸化窑 φ4500×45000", "source_type": "text",
             "drawing_id": "a", "score": 0.1},
            {"content": "酸化窑总图 图号 2024-001", "source_type": "title_field",
             "drawing_id": "b", "score": 0.05},
            {"content": "MILL-002 | 酸化窑", "source_type": "equipment",
             "drawing_id": "c", "score": 0.08},
        ]
        ranked = rerank("酸化窑", results, top_k=10)
        assert len(ranked) == 3
        # All have relevance field
        for r in ranked:
            assert "relevance" in r
        # Highest relevance first
        assert ranked[0]["relevance"] >= ranked[-1]["relevance"]

    def test_rerank_dedup(self):
        """Test that reranker demotes duplicates."""
        from src.rag.reranker import rerank

        results = [
            {"content": "酸化窑 φ4500", "source_type": "text",
             "drawing_id": "a", "score": 0.9},
            {"content": "酸化窑 φ4500", "source_type": "text",
             "drawing_id": "b", "score": 0.9},
        ]
        ranked = rerank("酸化窑", results, top_k=10)
        assert ranked[0]["relevance"] >= ranked[1]["relevance"]
