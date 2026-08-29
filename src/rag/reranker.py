"""Reranker — 重排序 (Phase 6).

Re-ranks hybrid retrieval results using a lightweight relevance model:
- Lexical overlap score (query tokens appearing in content)
- Diversity penalty for near-duplicate results
- Source-type prior (equipment/title_field rank higher than raw text)

Pure rule-based; no LLM required. Never invents content.
"""

from __future__ import annotations

import re

from src.utils.logger import setup_logger

logger = setup_logger("cadkb.rag.rerank")

# Source-type priors (multiplier applied to final score)
SOURCE_PRIOR = {
    "equipment": 1.15,
    "title_field": 1.10,
    "pipe": 1.05,
    "attribute": 1.0,
    "dimension": 0.95,
    "text": 0.9,
    "entity": 0.85,
    "drawing": 0.8,
}


def _tokenize(text: str) -> set[str]:
    """Simple tokenizer: CJK bigrams + alphanumeric tokens."""
    tokens: set[str] = set()
    for m in re.findall(r"[A-Za-z0-9]+|[一-龥]", text):
        tokens.add(m.lower())
    # CJK bigrams
    cjk = re.findall(r"[一-龥]{2,}", text)
    for phrase in cjk:
        for i in range(len(phrase) - 1):
            tokens.add(phrase[i : i + 2])
    return tokens


class Reranker:
    """Re-rank hybrid search results."""

    def rerank(self, query: str, results: list[dict], top_k: int = 10) -> list[dict]:
        """Re-rank results by relevance to the query.

        Args:
            query: User query string.
            results: List of hybrid search result dicts.
            top_k: Max results to return.

        Returns:
            Re-ranked results, each with a `relevance` field added.
        """
        if not results:
            return []

        q_tokens = _tokenize(query)
        if not q_tokens:
            for r in results:
                r["relevance"] = r.get("score", 0.0)
            ranked = sorted(results, key=lambda r: r["relevance"], reverse=True)
            return ranked[:top_k]

        for r in results:
            content = r.get("content", "")
            c_tokens = _tokenize(content)
            overlap = len(q_tokens & c_tokens)
            lex_ratio = overlap / max(len(q_tokens), 1)

            base = r.get("score", 0.0)
            prior = SOURCE_PRIOR.get(r.get("source_type", ""), 1.0)
            r["relevance"] = round(base * prior + 0.2 * lex_ratio, 4)

        # Diversity: demote exact duplicate contents
        seen: set[str] = set()
        ranked = []
        for r in sorted(results, key=lambda x: x["relevance"], reverse=True):
            content = r.get("content", "").strip().lower()
            if content in seen and content:
                r["relevance"] *= 0.9
            seen.add(content)
            ranked.append(r)

        ranked.sort(key=lambda r: r["relevance"], reverse=True)
        logger.info(f"重排序: {len(results)} → {min(top_k, len(ranked))} 条")
        return ranked[:top_k]


def rerank(query: str, results: list[dict], top_k: int = 10) -> list[dict]:
    """Convenience wrapper for Reranker().rerank()."""
    return Reranker().rerank(query, results, top_k)
