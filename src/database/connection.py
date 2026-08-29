"""Database connection and initialization."""

import json
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import get_config
from src.database.models import Base
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.database")

_engine = None
_SessionLocal = None


def get_engine():
    """Get or create the SQLAlchemy engine."""
    global _engine
    if _engine is None:
        config = get_config()
        db_path = config.db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{db_path}"
        _engine = create_engine(
            db_url,
            echo=False,
            connect_args={"check_same_thread": False},
        )
        logger.info(f"数据库引擎已创建: {db_path}")
    return _engine


def get_session() -> Session:
    """Get a new database session."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal()


def reset_engine():
    """Reset the engine and session factory (for testing)."""
    global _engine, _SessionLocal
    if _engine:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def init_database():
    """Create all tables and FTS indexes."""
    engine = get_engine()

    # Create all ORM tables
    Base.metadata.create_all(engine)
    logger.info("ORM 表已创建")

    # Create FTS5 full-text indexes (SQLite specific)
    with engine.connect() as conn:
        # Text content FTS
        try:
            conn.execute(text("""
                CREATE VIRTUAL TABLE IF NOT EXISTS texts_fts USING fts5(
                    text_content,
                    drawing_id UNINDEXED,
                    entity_id UNINDEXED,
                    layer UNINDEXED,
                    layout UNINDEXED,
                    tokenize='unicode61'
                )
            """))
            conn.commit()
        except Exception as e:
            logger.warning(f"FTS5 texts_fts 创建失败 (可能不支持): {e}")

        # Block attributes FTS
        try:
            conn.execute(text("""
                CREATE VIRTUAL TABLE IF NOT EXISTS attributes_fts USING fts5(
                    tag,
                    value,
                    drawing_id UNINDEXED,
                    block_name UNINDEXED,
                    tokenize='unicode61'
                )
            """))
            conn.commit()
        except Exception as e:
            logger.warning(f"FTS5 attributes_fts 创建失败: {e}")

        # Drawings FTS
        try:
            conn.execute(text("""
                CREATE VIRTUAL TABLE IF NOT EXISTS drawings_fts USING fts5(
                    file_name,
                    notes,
                    drawing_id UNINDEXED,
                    tokenize='unicode61'
                )
            """))
            conn.commit()
        except Exception as e:
            logger.warning(f"FTS5 drawings_fts 创建失败: {e}")

        # Documents FTS (Phase 5: 非 CAD 文件内容全文索引)
        try:
            conn.execute(text("""
                CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                    title,
                    content,
                    file_id UNINDEXED,
                    source_type UNINDEXED,
                    tokenize='unicode61'
                )
            """))
            conn.commit()
        except Exception as e:
            logger.warning(f"FTS5 documents_fts 创建失败: {e}")

    logger.info("数据库初始化完成")


def reset_database():
    """Drop all tables and recreate (use with caution!)."""
    engine = get_engine()
    Base.metadata.drop_all(engine)
    # Also drop FTS tables
    with engine.connect() as conn:
        for fts_table in ["texts_fts", "attributes_fts", "drawings_fts"]:
            try:
                conn.execute(text(f"DROP TABLE IF EXISTS {fts_table}"))
                conn.commit()
            except Exception:
                pass
    init_database()
    logger.warning("数据库已重置 — 所有表已重建")
