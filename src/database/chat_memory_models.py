"""SQLAlchemy models for project chat memory (Chat Memory Hub).

Tables:
- conversations : one row per chat session (title / summary / source file)
- messages      : full user/assistant message text (FTS5-indexed)
- ingest_state  : per-file ingestion watermark (mtime/size) for incremental scan
"""

from datetime import datetime

from sqlalchemy import (
    Column, String, Integer, Float, Text, DateTime, Index,
)

from src.database.models import Base


class ConversationModel(Base):
    """Chat session metadata."""
    __tablename__ = "conversations"

    conversation_id = Column(String, primary_key=True)   # conversationId / sessionId
    title = Column(String, default="")                   # ai-title or first user msg
    source_file = Column(String, default="")             # relative jsonl path
    started_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    msg_count = Column(Integer, default=0)               # total user+assistant messages
    user_msg_count = Column(Integer, default=0)          # questions asked
    summary = Column(Text, default="")                   # rule-based summary
    keywords = Column(Text, default="")                  # top keywords (JSON list)
    files_mentioned = Column(Text, default="")           # file paths found (JSON list)

    __table_args__ = (
        Index("idx_conv_updated", "updated_at"),
        Index("idx_conv_title", "title"),
    )


class MessageModel(Base):
    """One chat message (user or assistant)."""
    __tablename__ = "messages"

    msg_id = Column(String, primary_key=True)            # jsonl line id
    conversation_id = Column(String, nullable=False)
    role = Column(String, nullable=False)                # user / assistant
    content = Column(Text, default="")
    seq = Column(Integer, default=0)                     # order within conversation
    timestamp = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_msg_conv", "conversation_id"),
        Index("idx_msg_role", "role"),
    )


class IngestStateModel(Base):
    """Incremental ingestion watermark: skip files whose mtime/size unchanged."""
    __tablename__ = "ingest_state"

    file_path = Column(String, primary_key=True)         # absolute jsonl path
    mtime = Column(Float, default=0.0)                   # last-seen file mtime
    size = Column(Integer, default=0)                    # last-seen file size
    lines_processed = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
