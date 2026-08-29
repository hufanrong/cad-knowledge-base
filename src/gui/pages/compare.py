"""图纸比较页面 — 差异报告 (Phase 10)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def render(st):
    st.title("📊 图纸比较")

    st.markdown(
        "比较两张 CAD 图纸（DXF/DWG 均可），展示实体、文字、尺寸和语义差异。"
    )

    c1, c2 = st.columns(2)
    path_a = c1.text_input("图纸 A 路径", placeholder="C:/drawings/A.dwg")
    path_b = c2.text_input("图纸 B 路径", placeholder="C:/drawings/B.dwg")

    if st.button("开始比较", type="primary"):
        if not path_a or not path_b:
            st.warning("请输入两个文件路径")
            return
        pa, pb = Path(path_a), Path(path_b)
        if not pa.exists() or not pb.exists():
            st.error("文件不存在，请检查路径")
            return

        with st.spinner("正在解析并比较图纸..."):
            try:
                report = _compare(pa, pb)
            except Exception as e:
                st.error(f"比较失败: {e}")
                return

        s = report.summary
        st.success(f"比较完成，共 {report.total_changes} 项变更")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("实体变更",
                  s["entities"]["added"] + s["entities"]["removed"] + s["entities"]["modified"])
        c2.metric("文字变更",
                  s["texts"]["added"] + s["texts"]["removed"] + s["texts"]["modified"])
        c3.metric("尺寸变更",
                  s["dimensions"]["added"] + s["dimensions"]["removed"] + s["dimensions"]["modified"])
        c4.metric("语义变更",
                  s["equipment"]["added"] + s["equipment"]["removed"] + s["title_fields"])

        tab_ent, tab_txt, tab_dim, tab_sem = st.tabs(["实体", "文字", "尺寸", "语义"])

        with tab_ent:
            if report.entity_added or report.entity_removed or report.entity_modified:
                rows = []
                for e in report.entity_added:
                    rows.append({"状态": "➕ 新增", "类型": e.entity_type, "图层": e.layer, "详情": e.detail})
                for e in report.entity_removed:
                    rows.append({"状态": "➖ 删除", "类型": e.entity_type, "图层": e.layer, "详情": e.detail})
                for e in report.entity_modified:
                    rows.append({"状态": "✏️ 修改", "类型": e.entity_type, "图层": e.layer, "详情": e.detail})
                st.dataframe(pd.DataFrame(rows), use_container_width=True)
            else:
                st.info("实体无差异")

        with tab_txt:
            if report.texts_added or report.texts_removed or report.texts_modified:
                rows = []
                for t in report.texts_added:
                    rows.append({"状态": "➕ 新增", "旧": "", "新": t.new_content, "图层": t.layer})
                for t in report.texts_removed:
                    rows.append({"状态": "➖ 删除", "旧": t.old_content, "新": "", "图层": t.layer})
                for t in report.texts_modified:
                    rows.append({"状态": "✏️ 修改", "旧": t.old_content, "新": t.new_content, "图层": t.layer})
                st.dataframe(pd.DataFrame(rows), use_container_width=True)
            else:
                st.info("文字无差异")

        with tab_dim:
            total_dim = (len(report.dimensions_added) + len(report.dimensions_removed)
                         + len(report.dimensions_modified))
            if total_dim > 0:
                rows = []
                for d in report.dimensions_added:
                    rows.append({"状态": "➕ 新增", "旧值": "", "新值": d.new_measurement, "文本": d.new_text})
                for d in report.dimensions_removed:
                    rows.append({"状态": "➖ 删除", "旧值": d.old_measurement, "新值": "", "文本": d.old_text})
                for d in report.dimensions_modified:
                    rows.append({"状态": "✏️ 修改", "旧值": d.old_measurement,
                                 "新值": d.new_measurement, "文本": f"{d.old_text} → {d.new_text}"})
                st.dataframe(pd.DataFrame(rows), use_container_width=True)
            else:
                st.info("尺寸无差异")

        with tab_sem:
            if report.equipment_added or report.equipment_removed or report.title_field_changes:
                rows = []
                for e in report.equipment_added:
                    rows.append({"类型": "设备", "状态": "➕ 新增", "内容": e})
                for e in report.equipment_removed:
                    rows.append({"类型": "设备", "状态": "➖ 删除", "内容": e})
                for t in report.title_field_changes:
                    rows.append({"类型": "标题栏", "状态": "✏️ 修改",
                                 "内容": f"[{t.detail}] {t.old_content} → {t.new_content}"})
                st.dataframe(pd.DataFrame(rows), use_container_width=True)
            else:
                st.info("语义无差异")


def _compare(pa: Path, pb: Path):
    """Parse two files and produce a compare report."""
    from src.compare import compare_drawings
    from src.file_manager.version_detector import get_file_info

    def parse(path: Path):
        info = get_file_info(path)
        ft = info["file_type"]
        if ft == "dwg":
            from src.parsers.dwg_parser import DWGParser
            result = DWGParser().parse(path)
        else:
            from src.parsers.dxf_parser import DXFParser
            result = DXFParser().parse(path)
        if result.drawing.parse_status != "success":
            raise RuntimeError(f"解析失败: {path} — {result.errors}")
        from src.semantic import analyze
        analyze(result)
        return result

    ra = parse(pa)
    rb = parse(pb)
    return compare_drawings(ra, rb, pa.name, pb.name)
