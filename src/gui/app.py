"""Streamlit GUI — 主应用入口 (Phase 10).

Run with: cadkb gui   (or)   streamlit run src/gui/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root on path when run via `streamlit run`
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from src.core.config import get_config  # noqa: E402
from src.database.connection import init_database  # noqa: E402


def main():
    st.set_page_config(
        page_title="CAD 知识库",
        page_icon="📐",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    config = get_config()
    config.ensure_directories()
    init_database()

    st.sidebar.title("📐 CAD 知识库")
    st.sidebar.caption("本地 CAD 图纸解析与私人知识库")

    pages = {
        "图纸导入": render_import,
        "图纸浏览": render_browse,
        "搜索": render_search,
        "AI 问答": render_qa,
        "图纸比较": render_compare,
        "数据校核": render_review,
        "2.5D 空间语义图": render_map,
        "批量导出": render_export,
    }
    choice = st.sidebar.radio("导航", list(pages.keys()))

    st.sidebar.divider()
    st.sidebar.caption("系统状态")
    try:
        from src.database.connection import get_session
        from src.database.repositories import DrawingRepository

        session = get_session()
        stats = DrawingRepository(session).get_database_stats()
        session.close()
        st.sidebar.write(f"图纸: {stats['drawings']}  实体: {stats['entities']}")
    except Exception:
        pass

    pages[choice]()


def render_import():
    from src.gui.pages.import_page import render
    render(st)


def render_browse():
    from src.gui.pages.browse import render
    render(st)


def render_search():
    from src.gui.pages.search import render
    render(st)


def render_qa():
    from src.gui.pages.qa import render
    render(st)


def render_compare():
    from src.gui.pages.compare import render
    render(st)


def render_review():
    from src.gui.pages.review import render
    render(st)


def render_map():
    from src.gui.pages.map_view import render
    render()


def render_export():
    from src.gui.pages.export import render
    render(st)


if __name__ == "__main__":
    main()
