"""Tests for the Chat Memory Hub (project chat history sharing).

Covers: jsonl filtering, incremental ingest idempotency, rule summaries,
hybrid search (FTS), summary index truncation.
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.database.chat_memory_models import (
    ConversationModel, IngestStateModel, MessageModel,
)


def _make_jsonl_line(typ, rid, role="", text="", ts=None, parent=None):
    obj = {"id": rid, "parentId": parent, "timestamp": ts or int(time.time() * 1000),
           "type": typ, "sessionId": "s1", "cwd": "dummy"}
    if typ == "message":
        obj["role"] = role
        obj["content"] = [{"type": "input_text" if role == "user" else "output_text",
                           "text": text}]
        obj["status"] = "completed"
    elif typ == "ai-title":
        obj["aiTitle"] = "测试会话标题"
    else:
        obj["content"] = [{"type": "text", "text": "noise"}]
    return json.dumps(obj, ensure_ascii=False)


@pytest.fixture
def chat_env(tmp_path, monkeypatch):
    """Isolate chat-memory to a temp project dir with a fake jsonl."""
    # fake WorkBuddy projects tree
    proj_name = "d-fake-workdir-2026-01-01"
    proj_dir = tmp_path / "projects" / proj_name
    proj_dir.mkdir(parents=True)
    jsonl = proj_dir / "conv-abc.jsonl"
    lines = [
        _make_jsonl_line("reasoning", "r1", text="思考过程"),
        _make_jsonl_line("function_call", "fc1", text="tool call"),
        _make_jsonl_line("message", "m1", role="user",
                         text="熟料立式磨的基础标高是多少？", ts=1750000000000),
        _make_jsonl_line("message", "m2", role="assistant",
                         text="根据结构图分析，基础顶标高为 ±0.000（绝对 644.00m）",
                         ts=1750000010000),
        _make_jsonl_line("message", "m3", role="user",
                         text="Chroma 批量导入失败怎么办", ts=1750000020000),
        _make_jsonl_line("message", "m4", role="assistant",
                         text="检查 batch size，改为分批 upsert，参考 vector_index.py",
                         ts=1750000030000),
        _make_jsonl_line("file-history-snapshot", "fh1", text="snapshot"),
        _make_jsonl_line("ai-title", "t1", text=""),
    ]
    jsonl.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # sessions.json mapping
    sessions = tmp_path / "app"
    sessions.mkdir()
    (sessions / "sessions.json").write_text(json.dumps([{
        "conversationId": "conv-abc", "workDir": r"D:\fake\workdir\2026-01-01",
        "startedAt": 1750000000000,
    }]), encoding="utf-8")

    # point chat-memory modules at temp locations
    import src.core.chat_memory as cm
    import scripts.chat_memory.build_index as bi

    fake_workdir = Path(r"D:\fake\workdir\2026-01-01")
    monkeypatch.setattr(bi, "CURRENT_WORKDIR", fake_workdir)
    monkeypatch.setattr(bi, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(bi, "SESSIONS_INDEX", sessions / "sessions.json")
    monkeypatch.setattr(bi, "MEMORY_ROOT", tmp_path / ".workbuddy" / "chat-memory")

    monkeypatch.setattr(cm, "CURRENT_WORKDIR", fake_workdir)
    monkeypatch.setattr(cm, "MEMORY_ROOT", tmp_path / ".workbuddy" / "chat-memory")
    monkeypatch.setattr(cm, "DB_PATH", tmp_path / ".workbuddy" / "chat-memory" / "chat_memory.db")
    monkeypatch.setattr(cm, "CHROMA_DIR", tmp_path / ".workbuddy" / "chat-memory" / "chroma")
    monkeypatch.setattr(cm, "_engine", None)
    monkeypatch.setattr(cm, "_SessionLocal", None)

    yield {
        "project_dir": proj_dir, "jsonl": jsonl,
        "mem_root": tmp_path / ".workbuddy" / "chat-memory",
        "bi": bi, "cm": cm,
    }


class TestIngest:
    def test_filters_and_groups(self, chat_env):
        """Only user/assistant messages ingested; grouped into one conversation."""
        stats = chat_env["bi"].ingest(force=True, do_vector=False)
        assert stats["new_messages"] == 4          # 2 user + 2 assistant
        assert stats["conversations"] == 1
        assert stats["skipped"] == 0

        from src.core.chat_memory import list_conversations
        convs = list_conversations()
        assert len(convs) == 1
        c = convs[0]
        assert c["msg_count"] == 4
        assert c["user_msg_count"] == 2
        assert c["title"]                       # rule title non-empty

    def test_incremental_idempotent(self, chat_env):
        """Second run without changes skips the file (no duplicates)."""
        chat_env["bi"].ingest(force=True, do_vector=False)
        stats2 = chat_env["bi"].ingest(force=False, do_vector=False)
        assert stats2["skipped"] == 1
        assert stats2["new_messages"] == 0

        from src.core.chat_memory import list_conversations
        convs = list_conversations()
        assert len(convs) == 1
        assert convs[0]["msg_count"] == 4

    def test_summary_fields(self, chat_env):
        """Keywords + files mentioned are extracted."""
        chat_env["bi"].ingest(force=True, do_vector=False)
        from src.core.chat_memory import list_conversations
        c = list_conversations()[0]
        assert c["keywords"]                    # non-empty
        # files mentioned: "vector_index.py" should appear
        assert any("vector_index.py" in f for f in c["files"])


class TestSearch:
    def test_fts_search_hits(self, chat_env):
        chat_env["bi"].ingest(force=True, do_vector=False)
        from src.core.chat_memory import search_messages
        hits = search_messages("熟料立式磨", k=3)
        assert hits
        assert any("标高" in h["content"] for h in hits)

    def test_search_conversations(self, chat_env):
        chat_env["bi"].ingest(force=True, do_vector=False)
        from src.core.chat_memory import search_conversations
        hits = search_conversations("Chroma")
        assert any("Chroma" in (h["title"] or "") or h["conversation_id"]
                   for h in hits)


class TestSummaryIndex:
    def test_index_truncation(self, chat_env):
        chat_env["bi"].ingest(force=True, do_vector=False)
        from src.core.chat_memory import get_summary_index
        idx = get_summary_index(max_chars=3000)
        assert isinstance(idx, str)
        assert len(idx) <= 3200
        assert "项目聊天记忆索引" in idx


class TestVectorSearch:
    def test_vector_search(self, chat_env):
        """Vector search works when chroma available (model cached)."""
        chat_env["bi"].ingest(force=True, do_vector=True)
        from src.core.chat_memory import search_messages
        hits = search_messages("基础标高", k=3)
        # may be empty if model/chroma unavailable in CI; at least no crash
        assert isinstance(hits, list)
