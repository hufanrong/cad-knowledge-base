"""搜索页面 — 综合搜索 + 空间区域搜索 (Phase 10)."""

from __future__ import annotations

import pandas as pd

from src.database.connection import get_session


def render(st):
    st.title("🔍 搜索")

    tab_search, tab_region = st.tabs(["综合搜索", "空间区域搜索"])

    with tab_search:
        _render_search_tab(st)

    with tab_region:
        _render_region_tab(st)


def _render_search_tab(st):
    query = st.text_input("关键词", placeholder="例如: 酸化窑, MILL-001, 2024-001")
    c1, c2 = st.columns([1, 3])
    search_type = c1.selectbox(
        "类型", ["all", "text", "attribute", "equipment", "title_field", "dimension"]
    )
    limit = c2.slider("结果数", 5, 100, 20)

    if st.button("搜索", type="primary"):
        if not query.strip():
            st.warning("请输入关键词")
            return

        from src.index.search_service import SearchService

        svc = SearchService()
        try:
            results = svc.search(
                query=query.strip(),
                search_type=search_type,
                limit=limit,
            )
        finally:
            svc.close()

        if not results:
            st.info("无结果")
            return

        st.success(f"找到 {len(results)} 条结果")
        df = pd.DataFrame([
            {
                "类型": r.result_type,
                "内容": r.content[:80],
                "文件": r.file_name,
                "图层": r.layer,
                "handle": r.handle,
                "得分": r.score,
            }
            for r in results
        ])
        st.dataframe(df, use_container_width=True)


def _render_region_tab(st):
    st.markdown("在指定坐标区域内搜索实体（bbox 空间查询）")
    c1, c2 = st.columns(2)
    min_x = c1.number_input("Min X", value=0.0)
    min_y = c1.number_input("Min Y", value=0.0)
    max_x = c2.number_input("Max X", value=1500.0)
    max_y = c2.number_input("Max Y", value=1500.0)

    from src.database.connection import get_session
    from src.database.models import EntityModel

    # 可选实体类型
    session = get_session()
    types = [
        r[0] for r in session.query(EntityModel.entity_type).distinct().all() if r[0]
    ]
    session.close()
    entity_types = st.multiselect(
        "实体类型过滤（可选）", sorted(types), default=[]
    )

    if st.button("区域搜索", type="primary"):
        from src.index.search_service import search_in_region

        results = search_in_region(
            min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y,
            entity_types=entity_types if entity_types else None,
            limit=100,
        )
        if not results:
            st.info("区域内无实体")
            return

        st.success(f"找到 {len(results)} 个实体")
        df = pd.DataFrame([
            {
                "类型": r.extra.get("entity_type", ""),
                "中心坐标": f"({r.x:.1f}, {r.y:.1f})",
                "图层": r.layer,
                "handle": r.handle,
                "文件": r.file_name,
            }
            for r in results
        ])
        st.dataframe(df, use_container_width=True)
