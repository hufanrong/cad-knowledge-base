"""Chat Memory ingest pipeline — scan project jsonl chat logs into shared SQLite + vectors.

Usage:
    python scripts/chat_memory/build_index.py [--force] [--no-vector]
    python -m src.cli.main chat-memory update

Steps:
    1. locate project conversation dir (sessions.json workDir match + sanitize fallback)
    2. scan *.jsonl (incl. subagents/*.jsonl), incremental via ingest_state
    3. stream-parse lines, keep only type=message (user/assistant)
    4. group by conversation -> rule-based summary
    5. write SQLite (conversations/messages) + FTS5
    6. embed messages -> independent Chroma (collection=chat_memory)
"""

import argparse
import json
import re
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import text as sa_text

from src.database.chat_memory_models import (
    ConversationModel, IngestStateModel, MessageModel,
)
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.chat_memory")

# 注意：项目路径是 junction（指向 D:\WorkBuddy\outputs\projects\...），
# 不要 .resolve() 展开，否则 projects/ 目录名不匹配
CURRENT_WORKDIR = Path(r"D:\hufanrong\Documents\workBudd\2026-08-17-14-05-54")
PROJECTS_ROOT = Path(r"D:\WorkBuddy\work\data\projects")
SESSIONS_INDEX = Path(r"D:\WorkBuddy\work\data\app\sessions.json")
MEMORY_ROOT = CURRENT_WORKDIR / ".workbuddy" / "chat-memory"


def get_cm_engine(db_path: Path):
    """Create engine for chat-memory SQLite (independent from main KB db)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )

# types to skip entirely
_SKIP_TYPES = {
    "reasoning", "function_call", "function_call_result",
    "file-history-snapshot", "ai-title",
}
_FILE_RE = re.compile(r"[\w\-.\\/]+\.(?:dwg|dxf|py|md|xlsx|xls|docx|doc|pdf|yaml|json|txt|csv)", re.I)
_KEYWORD_STOP = set("的了和与及或是在我你有他她它这那一个不很也还对就都而如果因为所以但是可以需要应该进行使用完成实现文件图纸系统数据项目工作资料内容记录")
_EN_STOP = set("the and for with from this that these those you your are was were have has had will would can could should may might not all any out into over under about after before between during including through within also very just more than then there their them they its it is am be been being do does did done what which who whom whose why how when where whether while as at by in of on to or if but so no yes nor etc result tool previous omitted disconnected status connector system reminder data role context summary memory user assistant message content output input text".split())
_SYS_TAG_RE = re.compile(r"<system-reminder[^>]*>.*?</system-reminder>", re.S)
_SYS_TAG_RE2 = re.compile(r"<omitted\s*/>|</?omitted>|<user_query[^>]*>|</?user_query>|<cb_summary>|</cb_summary>")
# 聊天记录中的系统注入字段名（历史摘要/工具调用残留），不作为关键词
_NOISE_TOKENS = {
    "previous_tool_call", "previous_assistant_message", "previous_user_message",
    "arguments", "tool_call", "tool_name", "omitted", "ssage", "hufanrong",
    "user_query", "assistant", "reasoning", "function_call", "result_id",
    "subagent", "message_id", "conversation_id", "context", "system", "reminder",
    "user_context", "workbuddy", "cadkb", "src", "file_path", "task_id",
}


def sanitize_dir(workdir: Path) -> str:
    return str(workdir).replace("\\", "-").replace(":", "").replace("/", "-")


def locate_project_dir() -> Path:
    """Map current workspace to its projects/ folder (junction-aware)."""
    # 1) sessions.json exact workDir match
    if SESSIONS_INDEX.exists():
        try:
            data = json.loads(SESSIONS_INDEX.read_text(encoding="utf-8"))
            for s in data if isinstance(data, list) else data.get("sessions", []):
                wd = (s.get("workDir") or "").replace("\\", "/").lower()
                if wd and (CURRENT_WORKDIR.as_posix().lower() in wd
                           or CURRENT_WORKDIR.resolve().as_posix().lower() in wd):
                    name = sanitize_dir(Path(s["workDir"]))
                    cand = PROJECTS_ROOT / name
                    if cand.is_dir():
                        return cand
        except Exception as e:
            logger.warning(f"sessions.json 解析失败: {e}")
    # 2) sanitize fallback — try original path, then resolved (junction) path
    for base in (CURRENT_WORKDIR, CURRENT_WORKDIR.resolve()):
        cand = PROJECTS_ROOT / sanitize_dir(base)
        if cand.is_dir():
            return cand
    raise FileNotFoundError(f"找不到项目对话目录（原始/解析路径均无匹配）")


def scan_jsonl_files(project_dir: Path) -> list[Path]:
    """Collect main + subagent jsonl files."""
    files = list(project_dir.glob("*.jsonl"))
    for sub in project_dir.glob("*/subagents/*.jsonl"):
        files.append(sub)
    # de-dup, sort by path
    return sorted(set(files))


def parse_messages(path: Path):
    """Yield (line_id, role, text, ts_ms) for type=message lines (streaming)."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("type") != "message":
                continue
            role = obj.get("role", "")
            if role not in ("user", "assistant"):
                continue
            text = ""
            for c in obj.get("content") or []:
                if isinstance(c, dict) and c.get("text"):
                    text += c["text"] + "\n"
            text = text.strip()
            # strip system-reminder blocks & omitted markers (context noise)
            text = _SYS_TAG_RE.sub("", text)
            text = _SYS_TAG_RE2.sub("", text)
            text = text.strip()
            if not text:
                continue
            yield (
                obj.get("id") or str(uuid.uuid4()),
                role,
                text,
                obj.get("timestamp"),
            )


def read_ai_title(path: Path) -> str:
    """Extract ai-title record from jsonl (best session title)."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("type") == "ai-title" and obj.get("aiTitle"):
                    return obj["aiTitle"]
    except Exception:
        pass
    return ""


def build_summary(messages: list[dict], ai_title: str = "") -> dict:
    """Rule-based summary: title / keywords / files / counts. No LLM."""
    # title priority: ai-title > first real user question
    title = ""
    if ai_title:
        title = ai_title[:40]
    if not title:
        for m in messages:
            if m["role"] == "user":
                cand = m["text"].strip().replace("\n", " ")[:40]
                cand = re.sub(r"^<[a-z_]+>|</?[a-z_]+>", "", cand).strip()
                if cand and not cand.startswith(("#", "<system", "[")):
                    title = cand
                    break
    if not title:
        user_texts = [m["text"] for m in messages if m["role"] == "user"]
        title = (user_texts[0].strip().replace("\n", " ")[:40]
                 if user_texts else "")
    all_text = "\n".join(m["text"] for m in messages)
    # keywords: top frequent tokens (2+ chars), drop stop words both zh & en
    freq: Counter = Counter()
    for tok in re.findall(r"[\u4e00-\u9fa5]{2,8}|[A-Za-z][A-Za-z0-9_-]{2,20}", all_text):
        t = tok.lower()
        if (t in _KEYWORD_STOP or t in _EN_STOP or t in _NOISE_TOKENS
                or t.isdigit()):
            continue
        freq[t] += 1
    keywords = [w for w, _ in freq.most_common(10)]
    # files mentioned
    files = list(dict.fromkeys(_FILE_RE.findall(all_text)))[:10]
    return {
        "title": title,
        "user_count": len([m for m in messages if m["role"] == "user"]),
        "keywords": keywords,
        "files": files,
    }


def ingest(force: bool = False, do_vector: bool = True) -> dict:
    """Run ingestion. Returns stats dict."""
    project_dir = locate_project_dir()
    MEMORY_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = MEMORY_ROOT / "chat_memory.db"
    # create tables
    from src.database.chat_memory_models import Base as CMBase

    engine = get_cm_engine(db_path)
    CMBase.metadata.create_all(engine)
    # ensure FTS5
    with engine.connect() as conn:
        conn.execute(sa_text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5("
            "content, role UNINDEXED, conversation_id UNINDEXED, tokenize='unicode61')"
        ))
        conn.commit()

    stats = {"files": 0, "new_messages": 0, "conversations": 0, "skipped": 0}
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    for f in scan_jsonl_files(project_dir):
        mtime = f.stat().st_mtime
        size = f.stat().st_size
        st = session.get(IngestStateModel, str(f))
        if not force and st and st.mtime == mtime and st.size == size:
            stats["skipped"] += 1
            continue

        # delete existing messages of this file first (re-ingest replaces)
        conv_ids = [c.conversation_id for c in session.query(ConversationModel)
                    .filter(ConversationModel.source_file == f.name).all()]
        if conv_ids:
            session.query(MessageModel).filter(
                MessageModel.conversation_id.in_(conv_ids)).delete()
            session.query(ConversationModel).filter(
                ConversationModel.source_file == f.name).delete()

        # group lines by sessionId / conversationId
        groups: dict[str, list[dict]] = defaultdict(list)
        seq_counter: dict[str, int] = defaultdict(int)
        for line_id, role, text, ts in parse_messages(f):
            cid = f.name.split(".")[0]          # <conversationId>.jsonl
            seq_counter[cid] += 1
            groups[cid].append({
                "id": line_id, "role": role, "text": text,
                "seq": seq_counter[cid], "ts": ts,
            })

        for cid, msgs in groups.items():
            ai_title = read_ai_title(f)
            summary = build_summary(msgs, ai_title)
            conv = ConversationModel(
                conversation_id=cid,
                title=summary["title"],
                source_file=f.name,
                msg_count=len(msgs),
                user_msg_count=summary["user_count"],
                summary="\n".join([
                    f"标题: {summary['title']}",
                    f"消息数: {len(msgs)}（用户 {summary['user_count']}）",
                    f"关键词: {'、'.join(summary['keywords'])}",
                    f"涉及文件: {'、'.join(summary['files']) if summary['files'] else '无'}",
                ]),
                keywords=json.dumps(summary["keywords"], ensure_ascii=False),
                files_mentioned=json.dumps(summary["files"], ensure_ascii=False),
            )
            session.add(conv)
            for m in msgs:
                session.add(MessageModel(
                    msg_id=m["id"],
                    conversation_id=cid,
                    role=m["role"],
                    content=m["text"],
                    seq=m["seq"],
                    timestamp=(datetime.fromtimestamp(m["ts"] / 1000)
                               if m["ts"] else None),
                ))
            stats["new_messages"] += len(msgs)
            stats["conversations"] += 1

        if st is None:
            session.add(IngestStateModel(file_path=str(f), mtime=mtime,
                                         size=size, lines_processed=0))
        else:
            st.mtime, st.size = mtime, size
        stats["files"] += 1
        session.commit()

    session.commit()
    session.close()

    # refresh FTS from messages
    with engine.connect() as conn:
        conn.execute(sa_text("DELETE FROM messages_fts"))
        rows = []
        s2 = SessionLocal()
        for m in s2.query(MessageModel).yield_per(500):
            rows.append({"c": m.content or "", "r": m.role or "",
                         "cid": m.conversation_id or ""})
        s2.close()
        if rows:
            conn.execute(
                sa_text("INSERT INTO messages_fts(content, role, conversation_id)"
                        " VALUES (:c, :r, :cid)"),
                rows,
            )
        conn.commit()

    # vector index (independent Chroma)
    if do_vector:
        stats["vectors"] = _build_vectors(db_path)

    logger.info(f"摄取完成: {stats}")
    return stats


def _build_vectors(db_path: Path) -> int:
    """Embed message contents into independent Chroma collection."""
    try:
        import chromadb
        from src.index.vector_index import embed_texts

        chroma_dir = MEMORY_ROOT / "chroma"
        chroma_dir.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(chroma_dir))
        col = client.get_or_create_collection(
            name="chat_memory", metadata={"hnsw:space": "cosine"})
        # clear & rebuild (simple, idempotent)
        try:
            col.delete(where={})
        except Exception:
            pass

        engine = get_cm_engine(db_path)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        msgs = session.query(MessageModel).yield_per(200)
        batch_ids, batch_texts, batch_meta = [], [], []
        n = 0
        for m in msgs:
            if not (m.content or "").strip():
                continue
            batch_ids.append(m.msg_id)
            batch_texts.append(m.content[:1000])
            batch_meta.append({
                "conversation_id": m.conversation_id or "",
                "role": m.role or "",
            })
            if len(batch_ids) >= 200:
                vecs = embed_texts(batch_texts)
                col.upsert(ids=batch_ids, embeddings=vecs,
                           documents=batch_texts, metadatas=batch_meta)
                n += len(batch_ids)
                batch_ids, batch_texts, batch_meta = [], [], []
        if batch_ids:
            vecs = embed_texts(batch_texts)
            col.upsert(ids=batch_ids, embeddings=vecs,
                       documents=batch_texts, metadatas=batch_meta)
            n += len(batch_ids)
        session.close()
        return n
    except Exception as e:
        logger.warning(f"向量索引跳过: {e}")
        return 0


def main():
    ap = argparse.ArgumentParser(description="Chat Memory ingest")
    ap.add_argument("--force", action="store_true", help="re-ingest all files")
    ap.add_argument("--no-vector", action="store_true", help="skip vector indexing")
    args = ap.parse_args()
    stats = ingest(force=args.force, do_vector=not args.no_vector)
    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
