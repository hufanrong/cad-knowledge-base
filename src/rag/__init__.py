"""RAG — 混合检索与重排序 (Phase 6) + 上下文构建 (Phase 7).

- Hybrid search: FTS5 + vector + structured, merged with RRF weights
- Rerank: lexical overlap + source prior + diversity
- Vector index: Chroma (with pure-Python n-gram fallback)
- Context builder: traceable context for QA
"""

from src.rag.context_builder import ContextBuilder, ContextItem, build_context
from src.rag.hybrid_search import HybridSearch, hybrid_search
from src.rag.reranker import Reranker, rerank

__all__ = [
    "HybridSearch",
    "hybrid_search",
    "Reranker",
    "rerank",
    "ContextBuilder",
    "ContextItem",
    "build_context",
]
