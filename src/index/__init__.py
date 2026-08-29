"""Search system — 全文搜索 / 结构化搜索 / 空间搜索 (Phase 5).

- Full-text: SQLite FTS5 over texts / attributes / drawings
- Structured: SQL queries on layers, entity types, equipment, title blocks
- Spatial: bbox region queries, near-entity queries, spatial relationship
  lookups
"""

from src.index.search_result import SearchResult
from src.index.search_service import (
    SearchService,
    search,
    search_in_region,
)

__all__ = [
    "SearchResult",
    "SearchService",
    "search",
    "search_in_region",
]
