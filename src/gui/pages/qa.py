"""AI 问答页面 — RAG 检索 + 来源追溯 (Phase 10)。"""

from __future__ import annotations

import pandas as pd

from src.core.project_filter import list_projects
from src.llm import get_llm_client
from src.qa import QAService


def render(st):
    st.title("🤖 AI 问答")

    llm = get_llm_client()
    if llm.available:
        st.info(f"LLM 已配置: {llm.model}")
    else:
        st.warning(
            "LLM 未配置 API Key，将以**证据模式**运行（仅展示检索到的上下文与来源，不生成回答）。"
            "可在 `config/default.yaml` 的 `llm.api_key` 配置。"
        )

    # 工程范围选择（2026-08-30：共享库已更定义为马诺诺项目专属，无平台级资料）
    try:
        projects = list_projects()
        options = {"": "全部资料"}
        for p in projects:
            options[p["project_id"]] = f"{p['name']}（{p['file_count']} 份）"
        sel = st.selectbox(
            "资料范围",
            list(options.keys()),
            format_func=lambda k: options[k],
            help="资料库当前为马诺诺项目专属；选择工程后仅检索该工程资料，不串其他工程。",
        )
    except Exception as e:
        st.caption(f"(工程列表加载失败，按平台级查询: {e})")
        sel = ""

    query = st.text_area(
        "你的问题",
        placeholder="例如: 酸化窑的直径是多少？",
        height=90,
    )
    top_k = st.slider("检索深度", 3, 15, 8)

    if st.button("提问", type="primary", disabled=not query.strip()):
        with st.spinner("正在检索知识库..."):
            qa = QAService(llm_client=llm)
            ans = qa.ask(query.strip(), top_k=top_k, project_id=sel)

        st.divider()

        if ans.mode == "llm":
            st.markdown("### 💬 回答")
            st.markdown(ans.answer)
        else:
            st.markdown("### 📋 证据模式")
            if ans.llm_error:
                st.caption(f"(LLM 调用失败: {ans.llm_error})")
            st.caption("未生成回答，以下为检索到的原始上下文：")

        st.markdown(
            f"### 🔗 来源追溯 "
            f"`{ans.traceable_count} 可追溯 / {ans.untraceable_count} 无法追溯`"
        )

        if ans.context_items:
            rows = []
            for i, item in enumerate(ans.context_items, start=1):
                src = item.source
                # 阶段 5：为图纸来源生成 2.5D 地图定位链接
                map_link = ""
                if src.drawing_id:
                    map_link = f"[🗺️ 2.5D图](?page=map&drawing_id={src.drawing_id})"
                rows.append({
                    "#": i,
                    "内容": item.content[:90],
                    "类型": item.source.entity_type or item.data_tier,
                    "文件": src.file,
                    "图层": src.layer,
                    "handle": src.entity_handle,
                    "置信度": round(item.confidence, 3),
                    "定位": map_link,
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True)

            with st.expander("查看完整来源信息 (JSON)"):
                import json
                payload = [
                    {
                        "content": c.content,
                        "source": c.source.model_dump(),
                        "data_tier": c.data_tier,
                        "confidence": c.confidence,
                    }
                    for c in ans.context_items
                ]
                st.json(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            st.info("未检索到相关内容")
