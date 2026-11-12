"""Vector index — 向量索引 (Phase 6).

Wraps ChromaDB for persistent vector storage and query. If chromadb is
not installed, falls back to an in-memory numpy cosine-similarity index
so the system remains usable (with a warning in the log).

Embedding generation:
- Primary: sentence-transformers with a local model (bge-small-zh-v1.5
  or similar). Model is downloaded once on first use.
- Fallback: character n-gram hashing (pure Python) — deterministic,
  offline, but weaker semantically. Never fabricates embeddings.

The fallback only changes *retrieval quality*, never data content.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.chunker.chunker import DocumentChunk
from src.core.config import get_config
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.index.vector")

# Embedding model names (HuggingFace). bge-small-zh is small & Chinese.
DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
FALLBACK_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"  # smaller multilingual

# N-gram hashing dimensions for the pure-Python fallback
HASH_DIM = 512
NGRAM_N = 2

_chroma_available: bool | None = None
_embedder: Any | None = None
_embedder_backend: str | None = None

# 工程映射缓存（drawing_id -> project_id / file_id -> project_id，懒加载）
_proj_map: dict[str, str] | None = None


def _load_proj_map() -> dict[str, str]:
    """从 cadkb.db files 表加载 project_id 映射（key=drawing_id 或 file_id）。"""
    global _proj_map
    if _proj_map is not None:
        return _proj_map
    m: dict[str, str] = {}
    try:
        import sqlite3
        from src.core.config import get_config
        db_path = get_config().db_path
        if Path(db_path).exists():
            db = sqlite3.connect(str(db_path))
            try:
                c = db.cursor()
                for r in c.execute(
                    "SELECT drawing_id, project_id FROM files "
                    "WHERE drawing_id IS NOT NULL AND drawing_id != ''"
                ).fetchall():
                    m[r[0]] = (r[1] or "").strip()
                for r in c.execute(
                    "SELECT file_id, project_id FROM files"
                ).fetchall():
                    m[r[0]] = (r[1] or "").strip()
            finally:
                db.close()
    except Exception as e:
        logger.warning(f"加载 project_id 映射失败（向量索引不带工程标签）: {e}")
    _proj_map = m
    return _proj_map


def resolve_project_id(drawing_id: str, source_type: str = "") -> str:
    """按 drawing_id/file_id 解析工程 id（查 files 表），未命中返回空（平台级）。"""
    if not drawing_id:
        return ""
    # CAD 块用 drawing_id 映射；document 块 drawing_id 槽位存的就是 file_id，同样查
    return _load_proj_map().get(drawing_id, "")


def _check_chroma() -> bool:
    """Check whether chromadb is importable."""
    global _chroma_available
    if _chroma_available is None:
        try:
            import chromadb  # noqa: F401
            _chroma_available = True
        except ImportError:
            _chroma_available = False
    return _chroma_available


class NGramEmbedder:
    """Pure-Python character n-gram hashing embedder (fallback)."""

    dim = HASH_DIM

    def __init__(self) -> None:
        logger.warning(
            "使用 N-Gram 哈希向量（降级方案）。"
            "安装 chromadb + sentence-transformers 后可升级为语义向量。"
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * HASH_DIM
        chars = text.lower()
        for i in range(len(chars) - NGRAM_N + 1):
            gram = chars[i : i + NGRAM_N]
            h = int(hashlib.md5(gram.encode("utf-8")).hexdigest(), 16)
            vec[h % HASH_DIM] += 1.0
        # Normalize
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


def _get_embedder():
    """Get (lazily) the best available embedder."""
    global _embedder, _embedder_backend
    if _embedder is not None:
        return _embedder

    # Try sentence-transformers first
    try:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(DEFAULT_MODEL)
        _embedder_backend = "sentence-transformers"
        logger.info(f"Embedding 模型已加载: {DEFAULT_MODEL}")
        return _embedder
    except Exception as e:
        logger.warning(f"sentence-transformers 加载失败: {e}")

    # Fallback: n-gram hashing
    _embedder = NGramEmbedder()
    _embedder_backend = "ngram"
    return _embedder


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts into vectors.

    Returns list of float lists. Empty/whitespace texts yield zero vectors.
    """
    if not texts:
        return []
    emb = _get_embedder()
    try:
        if _embedder_backend == "sentence-transformers":
            vecs = emb.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            return [list(map(float, v)) for v in vecs]
        return emb.embed(texts)
    except Exception as e:
        logger.error(f"Embedding 生成失败: {e}")
        return [[0.0] * HASH_DIM for _ in texts]


class VectorIndex:
    """Vector index over document chunks."""

    def __init__(self, persist_dir: str | Path | None = None):
        config = get_config()
        self.persist_dir = Path(
            persist_dir or config.embeddings_dir
        )
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._collection = None
        self._client = None
        self._chunks: dict[str, DocumentChunk] = {}  # chunk_id -> chunk
        self._vectors: dict[str, list[float]] = {}  # chunk_id -> vector

    @property
    def backend(self) -> str:
        if _check_chroma():
            return "chroma"
        return "memory"

    def _ensure_collection(self):
        """Lazily open the Chroma collection (if available)."""
        if self._collection is not None:
            return
        if not _check_chroma():
            return
        try:
            import chromadb
            self._client = chromadb.PersistentClient(path=str(self.persist_dir))
            self._collection = self._client.get_or_create_collection(
                name="cadkb_chunks",
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            logger.warning(f"Chroma 初始化失败，使用内存索引: {e}")
            self._collection = None

    # ── indexing ────────────────────────────────────────────────────

    def index_chunks(self, chunks: list[DocumentChunk]) -> int:
        """Embed and store chunks.

        Returns number of chunks indexed.
        """
        if not chunks:
            return 0

        self._ensure_collection()
        texts = [c.content for c in chunks]
        vectors = embed_texts(texts)

        # Keep local copies for memory fallback
        for c, vec in zip(chunks, vectors):
            self._chunks[c.chunk_id] = c
            self._vectors[c.chunk_id] = vec

        if self._collection is not None:
            try:
                # chromadb 单次 upsert 有 batch 上限（默认 5000 左右），分批写入
                BATCH = 2000
                for i in range(0, len(chunks), BATCH):
                    batch = chunks[i:i + BATCH]
                    self._collection.upsert(
                        ids=[c.chunk_id for c in batch],
                        embeddings=vectors[i:i + BATCH],
                        documents=[c.content for c in batch],
                        metadatas=[
                            {
                                "drawing_id": c.drawing_id,
                                "source_type": c.source_type,
                                "entity_id": c.entity_id,
                                "handle": c.handle or "",
                                "layer": c.layer or "",
                                "layout": c.layout or "",
                                # 工程标签（P1）：按 files 表反查；未命中=平台级
                                "project_id": resolve_project_id(
                                    c.drawing_id, c.source_type),
                            }
                            for c in batch
                        ],
                    )
            except Exception as e:
                logger.warning(f"Chroma upsert 失败，仅内存索引: {e}")
        logger.info(f"向量索引: 已索引 {len(chunks)} 个块 (backend={self.backend})")
        return len(chunks)

    def delete_drawing(self, drawing_id: str) -> int:
        """Remove all chunks of a drawing from the index."""
        self._ensure_collection()

        # Remove from memory maps
        removed = [
            cid for cid, c in self._chunks.items()
            if c.drawing_id == drawing_id
        ]
        for cid in removed:
            self._chunks.pop(cid, None)
            self._vectors.pop(cid, None)

        if self._collection is not None:
            try:
                self._collection.delete(where={"drawing_id": drawing_id})
            except Exception as e:
                logger.warning(f"Chroma delete 失败: {e}")
        return len(removed)

    # ── query ───────────────────────────────────────────────────────

    def query(
        self,
        query_text: str,
        top_k: int = 10,
        where: dict | None = None,
    ) -> list[dict]:
        """Vector similarity search.

        Returns:
            List of dicts: {chunk_id, content, drawing_id, source_type,
            handle, layer, score, metadata}.
        """
        self._ensure_collection()
        vec = embed_texts([query_text])[0]

        if self._collection is not None:
            try:
                res = self._collection.query(
                    query_embeddings=[vec],
                    n_results=top_k,
                    where=where,
                )
                ids = res["ids"][0]
                distances = res["distances"][0]
                documents = res["documents"][0]
                metadatas = res["metadatas"][0]
                out = []
                for i, cid in enumerate(ids):
                    m = metadatas[i] or {}
                    out.append({
                        "chunk_id": cid,
                        "content": documents[i] if i < len(documents) else "",
                        "drawing_id": m.get("drawing_id", ""),
                        "source_type": m.get("source_type", ""),
                        "handle": m.get("handle", ""),
                        "layer": m.get("layer", ""),
                        "score": round(float(1 - distances[i]), 4),
                        "metadata": m,
                    })
                return out
            except Exception as e:
                logger.warning(f"Chroma query 失败，使用内存索引: {e}")

        # Memory fallback: cosine similarity over stored vectors
        import math

        results = []
        for cid, v in self._vectors.items():
            c = self._chunks[cid]
            if not _match_where(c, where):
                continue
            sim = _cosine(vec, v)
            results.append({
                "chunk_id": cid,
                "content": c.content,
                "drawing_id": c.drawing_id,
                "source_type": c.source_type,
                "handle": c.handle or "",
                "layer": c.layer or "",
                "score": round(sim, 4),
                "metadata": {"source_type": c.source_type},
            })
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    def query_project(
        self,
        query_text: str,
        top_k: int = 10,
        project_id: str = "",
        where: dict | None = None,
    ) -> list[dict]:
        """工程隔离向量查询（P1）：平台级 + 本工程 两次等值查询合并。

        规避 Chroma 1.5.9 bug：$in/$or 列表含空字符串 "" 时非空值全部丢失。
        改为 project_id 等值查询两次（本工程 / 平台级空串）合并去重。
        project_id 空 = 平台级查询（不隔离）。
        """
        if not project_id:
            return self.query(query_text, top_k=top_k, where=where)
        n = max(top_k * 2, 20)
        w_proj = self._compose_where(where, "project_id", project_id)
        w_plat = self._compose_where(where, "project_id", "")
        # 工程级结果轻度加权（×1.15）：避免平台级大库挤占工程资料，同时不严重扭曲排序
        proj_results = [
            {**r, "score": round(r.get("score", 0) * 1.15, 4)}
            for r in self.query(query_text, top_k=n, where=w_proj)
        ]
        plat_results = self.query(query_text, top_k=n, where=w_plat)
        merged = proj_results + plat_results
        seen: set[str] = set()
        out: list[dict] = []
        for r in merged:
            cid = r.get("chunk_id")
            if cid in seen:
                continue
            seen.add(cid)
            out.append(r)
        out.sort(key=lambda x: x.get("score", 0), reverse=True)
        return out[:top_k]

    @staticmethod
    def _compose_where(where: dict | None, field: str, value) -> dict:
        """把等值条件合并进既有 where（无 where 时直接等值）。"""
        if not where:
            return {field: value}
        return {"$and": [where, {field: value}]}

    def count(self) -> int:
        self._ensure_collection()
        if self._collection is not None:
            try:
                return self._collection.count()
            except Exception:
                pass
        return len(self._chunks)


def _match_where(chunk: "DocumentChunk", where: dict | None) -> bool:
    """内存兜底检索的 where 匹配（支持 $and / 等值 / project_id $in）。

    覆盖字段：drawing_id / source_type / project_id（后两者含反查）。
    """
    if not where:
        return True
    if "$and" in where:
        return all(_match_where(chunk, w) for w in where["$and"])
    for k, v in where.items():
        if k == "drawing_id":
            val = chunk.drawing_id
        elif k == "source_type":
            val = chunk.source_type
        elif k == "project_id":
            val = resolve_project_id(chunk.drawing_id, chunk.source_type)
        else:
            val = getattr(chunk, k, "") or ""
        if isinstance(v, dict) and "$in" in v:
            if val not in v["$in"]:
                return False
        elif val != v:
            return False
    return True


def _cosine(a: list[float], b: list[float]) -> float:
    import math

    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
