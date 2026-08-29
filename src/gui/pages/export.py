"""批量导出页：设备档案 Excel（阶段6）。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.core.export_service import export_device_profiles


def render(st):
    st.header("📥 批量导出")
    st.caption("将设备档案、候选关系等导出为 Excel，便于外部校核或汇报。")

    subsystem = st.text_input("按子系统过滤（留空导出全部）", "", key="export_subsystem")
    out_dir = Path("D:/WorkBuddy/work/data/knowledge_base/Temp/exports")
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    sub = subsystem.strip() or "all"
    default_name = f"device_profiles_{sub}_{ts}.xlsx"
    out_name = st.text_input("文件名", default_name, key="export_filename")
    out_path = out_dir / out_name

    if st.button("导出设备档案 Excel", key="export_btn"):
        with st.spinner("正在导出..."):
            path = export_device_profiles(out_path, subsystem_no=subsystem.strip() or None)
        st.success(f"导出完成：{path}")
        with open(path, "rb") as f:
            st.download_button(
                label="下载 Excel",
                data=f,
                file_name=path.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
