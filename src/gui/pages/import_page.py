"""图纸导入页面 — 导入 DXF/DWG 文件 (Phase 10)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd


def render(st):
    st.title("📥 图纸导入")

    st.markdown(
        "将 CAD 图纸（DXF / DWG）导入知识库。导入后自动执行：解析 → 语义分析"
        "（图框/标题栏/设备/管道）→ 空间关系 → 向量索引（供 AI 问答使用）。"
    )

    tab_file, tab_folder = st.tabs(["导入单个文件", "批量导入目录"])

    with tab_file:
        _render_single(st)

    with tab_folder:
        _render_folder(st)


def _render_single(st):
    uploaded = st.file_uploader(
        "选择 CAD 文件（DXF / DWG）",
        type=["dxf", "dwg"],
        help="支持 DXF 直接解析；DWG 需要 ODA File Converter（已检测到则自动转换）",
    )

    if uploaded is None:
        st.info("请先选择文件")
        return

    if st.button("导入", type="primary"):
        from src.file_manager.importer import import_file

        # Save upload to a temp file
        suffix = Path(uploaded.name).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded.getvalue())
            tmp_path = tmp.name

        try:
            with st.spinner(f"正在导入 {uploaded.name}..."):
                result = import_file(tmp_path)
            _render_result(st, result, uploaded.name)
        finally:
            Path(tmp_path).unlink(missing_ok=True)


def _render_folder(st):
    folder = st.text_input(
        "图纸目录路径",
        placeholder="C:/drawings 或 D:/CAD图纸",
        help="导入该目录下所有 DXF/DWG 文件",
    )
    recursive = st.checkbox("包含子目录", value=True)
    force = st.checkbox("强制重新导入（覆盖已存在）", value=False)

    if st.button("批量导入", type="primary", disabled=not folder):
        path = Path(folder)
        if not path.exists() or not path.is_dir():
            st.error(f"目录不存在: {folder}")
            return

        from src.file_manager.importer import import_directory

        with st.spinner(f"正在导入目录 {folder}..."):
            results = import_directory(path, recursive=recursive, force=force)

        success = sum(1 for r in results if r.get("status") == "success")
        dup = sum(1 for r in results if r.get("status") == "duplicate")
        failed = sum(1 for r in results if r.get("status") in ("error", "failed"))

        st.success(f"共 {len(results)} 个文件：成功 {success}，重复 {dup}，失败 {failed}")

        if results:
            rows = [
                {
                    "文件": r.get("file_name", "?"),
                    "状态": r.get("status", "?"),
                    "实体数": r.get("entity_count", 0),
                    "完整度": f"{r.get('completeness', 0) * 100:.0f}%",
                    "信息": (r.get("message") or "")[:40],
                }
                for r in results
            ]
            st.dataframe(pd.DataFrame(rows), use_container_width=True)


def _render_result(st, result: dict, display_name: str):
    status = result.get("status", "unknown")

    if status == "success":
        st.success(f"导入成功: {display_name}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("实体", result.get("entity_count", 0))
        c2.metric("文字", result.get("text_count", 0))
        c3.metric("尺寸", result.get("dimension_count", 0))
        c4.metric("完整度", f"{result.get('completeness', 0) * 100:.0f}%")
        st.caption(f"Drawing ID: `{result.get('drawing_id', '?')}`")
        st.caption(f"CAD 版本: {result.get('cad_version_name', '?')}")
    elif status == "duplicate":
        st.warning(f"文件已存在（重复），跳过导入: {display_name}")
        st.caption(f"Drawing ID: `{result.get('drawing_id', '?')}`")
    else:
        st.error(f"导入失败: {display_name}")
        st.write(result.get("message", "未知错误"))
        errors = result.get("errors")
        if errors:
            st.write(errors)
