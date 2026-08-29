"""图纸浏览页面 — 图纸列表 + 详情 (Phase 10)."""

from __future__ import annotations

import pandas as pd

from src.database.connection import get_session
from src.database.repositories import DrawingRepository


def render(st):
    st.title("📁 图纸浏览")

    session = get_session()
    repo = DrawingRepository(session)
    drawings = repo.list_drawings(limit=1000)
    session.close()

    if not drawings:
        st.info("知识库为空。请先在命令行导入图纸：`cadkb import <file>`")
        return

    # 概览表格
    st.subheader(f"共 {len(drawings)} 张图纸")
    rows = [
        {
            "文件名": d.file_name,
            "类型": d.file_type,
            "版本": d.cad_version_name or d.cad_version or "?",
            "实体数": d.entity_count,
            "文字数": d.text_count,
            "完整度": f"{d.data_completeness * 100:.0f}%",
            "状态": d.parse_status,
        }
        for d in drawings
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True)

    # 选择图纸查看详情
    selected = st.selectbox(
        "选择图纸查看详情",
        options=[d.drawing_id for d in drawings],
        format_func=lambda did: next(
            d.file_name for d in drawings if d.drawing_id == did
        ),
    )

    if selected:
        _render_detail(st, repo, selected)


def _render_detail(st, repo, drawing_id: str):
    st.divider()
    session = repo.session
    d = repo.find_by_id(drawing_id)
    if not d:
        st.warning("图纸不存在")
        return

    st.subheader(f"📄 {d.file_name}")
    st.caption(f"Drawing ID: `{d.drawing_id}`  |  版本: {d.cad_version_name or '?'}  |  路径: `{d.file_path}`")

    # 缩略图
    thumb = d.thumbnail_path
    if thumb and __import__("pathlib").Path(thumb).exists():
        st.image(thumb, caption="预览", use_container_width=True)
    else:
        st.info("暂无预览图。运行 `python scripts/build_previews.py` 批量生成线框预览。")

    # 统计
    stats = repo.get_drawing_summary(drawing_id) or {}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("实体", stats.get("entity_count", 0))
    c2.metric("文字", stats.get("text_count", 0))
    c3.metric("尺寸", stats.get("dimension_count", 0))
    c4.metric("图层", stats.get("layer_count", 0))

    tab_entities, tab_texts, tab_dims, tab_semantic, tab_spatial = st.tabs(
        ["实体", "文字", "尺寸", "语义分析", "空间关系"]
    )

    with tab_entities:
        ents = repo.get_entities_by_drawing(drawing_id, limit=500)
        if ents:
            df = pd.DataFrame([
                {"类型": e.get("entity_type"), "图层": e.get("layer"),
                 "handle": e.get("handle"), "块": e.get("block_name", "")}
                for e in ents
            ])
            st.dataframe(df, use_container_width=True)
        else:
            st.info("无实体")

    with tab_texts:
        texts = repo.get_texts_by_drawing(drawing_id, limit=500)
        if texts:
            df = pd.DataFrame([
                {"内容": t.get("text_content", "")[:60], "图层": t.get("layer"),
                 "handle": t.get("handle", "")}
                for t in texts
            ])
            st.dataframe(df, use_container_width=True)
        else:
            st.info("无文字")

    with tab_dims:
        dims = repo.get_dimensions_by_drawing(drawing_id, limit=500)
        if dims:
            df = pd.DataFrame([
                {"类型": x.get("dimension_type", ""), "数值": x.get("measurement"),
                 "文本": (x.get("text_content") or "")[:40], "图层": x.get("layer", "")}
                for x in dims
            ])
            st.dataframe(df, use_container_width=True)
        else:
            st.info("无尺寸")

    with tab_semantic:
        _render_semantic(st, repo, drawing_id)

    with tab_spatial:
        rels = repo.get_relationships_by_drawing(drawing_id, limit=200)
        if rels:
            df = pd.DataFrame([
                {"关系": r.get("relationship_type"),
                 "实体A": f"{r.get('entity_a_type')} {r.get('entity_a_id', '')[:8]}",
                 "实体B": f"{r.get('entity_b_type')} {r.get('entity_b_id', '')[:8]}",
                 "距离": r.get("distance")}
                for r in rels
            ])
            st.dataframe(df, use_container_width=True)
        else:
            st.info("无空间关系")


def _render_semantic(st, repo, drawing_id: str):
    # 图框
    frames = repo.get_frames_by_drawing(drawing_id)
    if frames:
        st.markdown("**图框**")
        for f in frames:
            st.write(
                f"尺寸 {f.get('width', 0):.0f}×{f.get('height', 0):.0f} "
                f"置信度 {f.get('confidence', 0):.2f}"
            )

    # 标题栏
    tbs = repo.get_title_blocks_by_drawing(drawing_id)
    if tbs:
        st.markdown("**标题栏**")
        fields = {}
        for tb in tbs:
            for f in tb.get("fields", []):
                if f.get("key"):
                    fields[f["key"]] = f.get("value", "")
        if fields:
            st.dataframe(pd.DataFrame(
                {"字段": list(fields.keys()), "值": list(fields.values())}
            ), use_container_width=True)

    # 设备
    eqs = repo.get_equipment_by_drawing(drawing_id)
    if eqs:
        st.markdown("**设备**")
        st.dataframe(pd.DataFrame([
            {"位号": e.get("equipment_no", ""), "名称": e.get("equipment_name", ""),
             "置信度": f"{e.get('confidence', 0):.2f}"}
            for e in eqs
        ]), use_container_width=True)

    # 管道
    pipes = repo.get_pipes_by_drawing(drawing_id)
    if pipes:
        st.markdown("**管道**")
        st.dataframe(pd.DataFrame([
            {"管线号": p.get("pipe_no", ""), "管径": p.get("diameter", ""),
             "材质": p.get("material", ""), "置信度": f"{p.get('confidence', 0):.2f}"}
            for p in pipes
        ]), use_container_width=True)

    if not frames and not tbs and not eqs and not pipes:
        st.info("无语义分析结果")
