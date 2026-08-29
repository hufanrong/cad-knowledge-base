"""Chat Memory Hub — retrieval service for project-wide chat history.

API:
    get_memory_root()          -> Path to .workbuddy/chat-memory
    list_conversations()       -> all conversations (id/title/time/counts)
    get_summary_index(max_chars) -> compact index text for MEMORY.md injection
    search_messages(q, k, cid) -> hybrid (FTS + vector) message search
    search_conversations(q)    -> conversations whose summary/keywords match
    ingest(force)              -> re-run ingest pipeline (delegates to build_index)
    update()                   -> ingest incremental + refresh MEMORY.md
"""

import json
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, or_, text as sa_text
from sqlalchemy.orm import sessionmaker

from src.database.chat_memory_models import ConversationModel, MessageModel
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.chat_memory")

CURRENT_WORKDIR = Path(r"D:\hufanrong\Documents\workBudd\2026-08-17-14-05-54").resolve()
MEMORY_ROOT = CURRENT_WORKDIR / ".workbuddy" / "chat-memory"
DB_PATH = MEMORY_ROOT / "chat_memory.db"
CHROMA_DIR = MEMORY_ROOT / "chroma"

_engine = None
_SessionLocal = None


def get_memory_root() -> Path:
    return MEMORY_ROOT


def _engine_impl():
    global _engine, _SessionLocal
    if _engine is None:
        MEMORY_ROOT.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{DB_PATH}", echo=False,
            connect_args={"check_same_thread": False})
        _SessionLocal = sessionmaker(bind=_engine)
    return _engine


def _session():
    _engine_impl()
    return _SessionLocal()


def _db_exists() -> bool:
    return DB_PATH.exists()


def list_conversations() -> list[dict]:
    if not _db_exists():
        return []
    s = _session()
    rows = s.query(ConversationModel).order_by(
        ConversationModel.updated_at.desc()).all()
    out = []
    for c in rows:
        out.append({
            "conversation_id": c.conversation_id,
            "title": c.title,
            "msg_count": c.msg_count,
            "user_msg_count": c.user_msg_count,
            "updated_at": c.updated_at.isoformat() if c.updated_at else "",
            "keywords": _safe_json(c.keywords, []),
            "files": _safe_json(c.files_mentioned, []),
        })
    s.close()
    return out


def get_summary_index(max_chars: int = 3000) -> str:
    """Compact per-conversation index (title + counts + keywords) for memory injection."""
    if not _db_exists():
        return "（聊天记忆尚未建立：运行 `python scripts/chat_memory/build_index.py`）"
    s = _session()
    rows = s.query(ConversationModel).order_by(
        ConversationModel.updated_at.desc()).all()
    s.close()
    lines = [
        "# 项目聊天记忆索引",
        f"> 由 chat-memory 生成于 {datetime.now():%Y-%m-%d %H:%M} · 共 {len(rows)} 个会话",
        "",
    ]
    for c in rows:
        kw = "、".join(_safe_json(c.keywords, [])[:6])
        entry = (f"- [{c.title or c.conversation_id[:8]}] "
                 f"({c.msg_count}条/{c.user_msg_count}问) "
                 f"关键词: {kw if kw else '—'}")
        lines.append(entry)
        if sum(len(x) for x in lines) > max_chars:
            lines = lines[:-1]
            lines.append("…（更多会话见 chat-memory 检索）")
            break
    return "\n".join(lines)


def _safe_json(v, default):
    if not v:
        return default
    try:
        return json.loads(v)
    except Exception:
        return default


def _fts_search(s, q, k, cid=None):
    """Search messages: FTS5 MATCH (ASCII/keywords) + LIKE fallback (Chinese)."""
    qq = " ".join(q.strip().split())
    if not qq:
        return []
    hits = []
    # 1) FTS5 MATCH (reliable for ASCII / code tokens)
    try:
        params: dict = {"q": f'"{qq}"', "k": k}
        if cid:
            params["cid"] = cid
        sql = (
            "SELECT f.content, f.role, f.conversation_id, "
            "       bm25(messages_fts) AS score "
            "FROM messages_fts f "
        )
        if cid:
            sql += "WHERE f.conversation_id = :cid AND messages_fts MATCH :q "
        else:
            sql += "WHERE messages_fts MATCH :q "
        sql += "ORDER BY score LIMIT :k"
        rows = s.execute(sa_text(sql), params).fetchall()
        hits = [{
            "content": r[0], "role": r[1], "conversation_id": r[2],
            "score": float(r[3]), "method": "fts",
        } for r in rows]
    except Exception as e:
        logger.warning(f"FTS MATCH 失败: {e}")

    # 2) LIKE fallback (Chinese substring, unicode61 MATCH unreliable)
    if not hits:
        like = f"%{q}%"
        q2 = s.query(MessageModel).filter(MessageModel.content.like(like))
        if cid:
            q2 = q2.filter(MessageModel.conversation_id == cid)
        for m in q2.order_by(MessageModel.timestamp.desc()).limit(k).all():
            hits.append({
                "content": m.content or "",
                "role": m.role or "",
                "conversation_id": m.conversation_id or "",
                "score": 0.6, "method": "fts",
            })
    return hits


def _vector_search(q, k, cid=None):
    """Chroma vector search. Returns list of dict hits."""
    try:
        import chromadb
        from src.index.vector_index import embed_texts
    except Exception:
        return []
    if not CHROMA_DIR.exists():
        return []
    try:
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        col = client.get_collection("chat_memory")
        vec = embed_texts([q])[0]
        where = {"conversation_id": cid} if cid else None
        res = col.query(query_embeddings=[vec], n_results=k, where=where)
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        out = []
        for i, mid in enumerate(ids):
            m = metas[i] or {}
            out.append({
                "content": docs[i][:600] if docs[i] else "",
                "role": m.get("role", ""),
                "conversation_id": m.get("conversation_id", ""),
                "score": 1.0 - float(dists[i]) if dists else 0.5,
                "method": "vector",
            })
        return out
    except Exception as e:
        logger.warning(f"向量检索失败: {e}")
        return []


def search_messages(q: str, k: int = 5, cid: str | None = None) -> list[dict]:
    """Hybrid search: FTS + vector, merge & dedupe by msg id (content)."""
    if not _db_exists():
        return []
    s = _session()
    fts = _fts_search(s, q, k, cid)
    s.close()
    vec = _vector_search(q, k, cid)
    merged: dict[str, dict] = {}
    for h in fts + vec:
        key = h["conversation_id"] + "|" + h["content"][:60]
        if key in merged:
            prev = merged[key]
            if h["method"] == "vector" and prev["method"] == "fts":
                merged[key] = {**h, "score": prev["score"] * 0.9 + h["score"] * 0.1}
            continue
        merged[key] = h
    hits = sorted(merged.values(), key=lambda x: -x["score"])
    # enrich with conversation title
    s = _session()
    cids = {h["conversation_id"] for h in hits}
    titles = {}
    if cids:
        for c in s.query(ConversationModel).filter(
                ConversationModel.conversation_id.in_(cids)).all():
            titles[c.conversation_id] = c.title
    s.close()
    for h in hits:
        h["title"] = titles.get(h["conversation_id"], h["conversation_id"][:8])
    return hits[:k]


def search_conversations(q: str, limit: int = 10) -> list[dict]:
    """Find conversations whose title/summary/keywords contain q (substring)."""
    if not _db_exists():
        return []
    like = f"%{q}%"
    s = _session()
    rows = s.query(ConversationModel).filter(or_(
        ConversationModel.title.like(like),
        ConversationModel.summary.like(like),
        ConversationModel.keywords.like(like),
    )).order_by(ConversationModel.updated_at.desc()).limit(limit).all()
    out = [{
        "conversation_id": c.conversation_id,
        "title": c.title,
        "msg_count": c.msg_count,
        "updated_at": c.updated_at.isoformat() if c.updated_at else "",
    } for c in rows]
    s.close()
    return out


def ingest(force: bool = False) -> dict:
    """Run the ingest pipeline (import lazily to avoid heavy imports)."""
    from scripts.chat_memory.build_index import ingest as _ingest
    return _ingest(force=force)


def update() -> dict:
    """Ingest incremental + write summary index to project MEMORY.md."""
    stats = ingest(force=False)
    idx = get_summary_index(max_chars=3000)
    mem_file = CURRENT_WORKDIR / ".workbuddy" / "memory" / "MEMORY.md"
    mem_file.parent.mkdir(parents=True, exist_ok=True)

    # preserve hand-written USER-NOTES block if present
    user_notes = ""
    if mem_file.exists():
        try:
            old = mem_file.read_text(encoding="utf-8")
            m = re.search(
                r"<!-- USER-NOTES-START -->(.*?)<!-- USER-NOTES-END -->",
                old, re.S)
            if m:
                user_notes = ("<!-- USER-NOTES-START -->"
                              + m.group(1)
                              + "<!-- USER-NOTES-END -->\n\n")
        except Exception:
            pass

    header = "<!-- chat-memory 自动生成，勿手改：会话精简索引（按需检索用 search） -->\n\n"
    try:
        mem_file.write_text(user_notes + header + idx + "\n", encoding="utf-8")
        stats["memory_updated"] = str(mem_file)
    except Exception as e:
        logger.warning(f"MEMORY.md 写入失败: {e}")
        stats["memory_updated"] = f"failed: {e}"
    return stats
