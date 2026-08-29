"""Hybrid search — 混合检索 (Phase 6).

Combines:
1. Keyword full-text search (SQLite FTS5)
2. Vector semantic search (Chroma / memory fallback)
3. Structured search (equipment / title fields)

Results are merged, deduplicated by chunk/entity identity, and scored
with reciprocal rank fusion (RRF) + weighted combination.
"""

from __future__ import annotations

from src.index.search_service import SearchService
from src.index.search_result import SearchResult
from src.index.vector_index import VectorIndex
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.rag.hybrid")


class HybridSearch:
    """Unified hybrid retrieval."""

    # Weight of each signal in the final score (0-1)
    FTS_WEIGHT = 0.4
    VECTOR_WEIGHT = 0.5
    STRUCTURED_WEIGHT = 0.3

    def __init__(self, vector_index: VectorIndex | None = None):
        self.search_service = SearchService()
        self.vector_index = vector_index or VectorIndex()

    def close(self):
        self.search_service.close()

    def search(
        self,
        query: str,
        top_k: int = 10,
        where: dict | None = None,
    ) -> list[dict]:
        """Run hybrid search and return merged, ranked results.

        Returns:
            List of dicts:
            {
              "content": str, "source_type": str, "drawing_id": str,
              "handle": str, "layer": str, "score": float,
              "fts_score": float|None, "vector_score": float|None,
              "metadata": dict,
            }
        """
        # 1. Keyword search (FTS) over texts & attributes
        fts_results: list[SearchResult] = []
        try:
            fts_results = self.search_service.search(
                query=query, search_type="text", limit=top_k * 3,
            )
            fts_results += self.search_service.search(
                query=query, search_type="attribute", limit=top_k * 3,
            )
        except Exception as e:
            logger.warning(f"FTS 检索失败: {e}")

        # 2. Vector search
        vector_results: list[dict] = []
        try:
            vector_results = self.vector_index.query(query, top_k=top_k * 3, where=where)
        except Exception as e:
            logger.warning(f"向量检索失败: {e}")

        # 3. Structured search (equipment / title fields)
        structured_results: list[SearchResult] = []
        try:
            structured_results = self.search_service.search(
                query=query, search_type="equipment", limit=top_k * 2,
            )
            structured_results += self.search_service.search(
                query=query, search_type="title_field", limit=top_k * 2,
            )
        except Exception as e:
            logger.warning(f"结构化检索失败: {e}")

        # Merge by content identity (normalized lower)
        merged: dict[str, dict] = {}

        def add_fts(r: SearchResult):
            key = f"fts:{r.result_type}:{r.drawing_id}:{r.content}".lower()
            if key in merged:
                merged[key]["fts_score"] = max(
                    merged[key].get("fts_score") or 0, r.score
                )
                return
            merged[key] = {
                "content": r.content,
                "source_type": r.result_type,
                "drawing_id": r.drawing_id,
                "handle": r.handle or "",
                "layer": r.layer or "",
                "score": r.score * self.FTS_WEIGHT,
                "fts_score": r.score,
                "vector_score": None,
                "metadata": {"file_name": r.file_name},
            }

        def add_vector(v: dict):
            key = f"vec:{v['source_type']}:{v['drawing_id']}:{v['content']}".lower()
            if key in merged:
                merged[key]["vector_score"] = max(
                    merged[key].get("vector_score") or 0, v["score"]
                )
                return
            merged[key] = {
                "content": v["content"],
                "source_type": v["source_type"],
                "drawing_id": v["drawing_id"],
                "handle": v.get("handle", "") or "",
                "layer": v.get("layer", "") or "",
                "score": v["score"] * self.VECTOR_WEIGHT,
                "fts_score": None,
                "vector_score": v["score"],
                "metadata": v.get("metadata", {}),
            }

        def add_structured(r: SearchResult):
            key = f"str:{r.result_type}:{r.drawing_id}:{r.content}".lower()
            if key in merged:
                merged[key]["score"] = max(merged[key]["score"], r.score * self.STRUCTURED_WEIGHT)
                return
            merged[key] = {
                "content": r.content,
                "source_type": r.result_type,
                "drawing_id": r.drawing_id,
                "handle": r.handle or "",
                "layer": r.layer or "",
                "score": r.score * self.STRUCTURED_WEIGHT,
                "fts_score": None,
                "vector_score": None,
                "metadata": {"file_name": r.file_name},
            }

        for r in fts_results:
            add_fts(r)
        for v in vector_results:
            add_vector(v)
        for r in structured_results:
            add_structured(r)

        # If a result matched in multiple channels, boost the score
        for item in merged.values():
            channels = 1
            if item["fts_score"] is not None:
                channels += 1
            if item["vector_score"] is not None:
                channels += 1
            item["score"] = round(item["score"] * (1 + 0.15 * (channels - 1)), 4)

        ranked = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
        logger.info(
            f"混合检索: '{query}' → {len(ranked)} 个唯一结果 "
            f"(fts={len(fts_results)}, vector={len(vector_results)}, "
            f"structured={len(structured_results)})"
        )
        return ranked[:top_k]


def hybrid_search(
    query: str,
    top_k: int = 10,
    vector_index: VectorIndex | None = None,
) -> list[dict]:
    """Convenience wrapper for HybridSearch.search()."""
    hs = HybridSearch(vector_index=vector_index)
    try:
        return hs.search(query, top_k=top_k)
    finally:
        hs.close()
