"""2.5D 空间语义图页面（阶段 4 + 阶段 5 MVP）。

布局：
- 左侧边栏：子系统选择、图纸列表、标高筛选
- 中间：底图 + 热区叠加（components.v1.html）
- 右侧：点击设备后弹出设备档案面板

交互：
- 热区点击通过 query param 回调（?page=map&drawing_id=...&tag=...）
- 页面读取 query params 显示档案侧栏
- 悬浮提示在 HTML/CSS 中实现（阶段 5 增强为供应商/箱号）
"""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from src.core.device_profile import get_device_profile
from src.core.map_service import (
    list_drawings_by_elevation,
    list_drawings_for_subsystem,
    list_subsystems,
    get_map_data,
)
from src.gui.map_renderer import render_map_html


def _sync_query_params():
    """从 URL query params 同步 drawing_id / tag。"""
    q = st.query_params
    if "drawing_id" in q:
        st.session_state["map_drawing_id"] = q["drawing_id"]
    if "tag" in q:
        st.session_state["map_selected_tag"] = q["tag"]


def _set_query_param(key: str, value: str):
    """更新 query param 并触发重载。"""
    params = st.query_params.to_dict()
    params[key] = value
    st.query_params.from_dict(params)


def _clear_tag():
    """清除 tag 参数。"""
    params = st.query_params.to_dict()
    params.pop("tag", None)
    st.query_params.from_dict(params)


def render():
    """Streamlit 页面入口（无参数，使用全局 st）。"""
    _sync_query_params()

    st.title("2.5D 空间语义图")

    # ── 左侧筛选 ──
    subsystems = list_subsystems(limit=200)
    if not subsystems:
        st.warning("暂无子系统数据，请先运行 scripts/build_equipment_tags.py")
        return

    sub_options = {s["subsystem_no"]: f"{s['subsystem_no']} ({s['drawing_count']}图/{s['tag_count']}位号)" for s in subsystems}

    default_sub = st.session_state.get("map_subsystem", subsystems[0]["subsystem_no"])
    subsystem = st.sidebar.selectbox(
        "选择子系统",
        options=list(sub_options.keys()),
        format_func=lambda k: sub_options.get(k, k),
        key="map_subsystem",
        index=list(sub_options.keys()).index(default_sub) if default_sub in sub_options else 0,
    )

    drawings = list_drawings_for_subsystem(subsystem)
    if not drawings:
        st.sidebar.warning("该子系统下无可用图纸")
        return

    default_did = st.session_state.get("map_drawing_id", drawings[0]["drawing_id"])
    drawing_index = next((i for i, d in enumerate(drawings) if d["drawing_id"] == default_did), 0)
    drawing = st.sidebar.selectbox(
        "选择图纸",
        options=drawings,
        format_func=lambda d: f"{d['file_name'][:40]} [{d['tag_count']}位号]" + (" ✅已校核标高" if d.get("elevation") else ""),
        index=drawing_index,
        key="map_drawing",
    )
    drawing_id = drawing["drawing_id"]
    st.session_state["map_drawing_id"] = drawing_id

    if drawing.get("elevation"):
        st.sidebar.info(f"标高基准：{drawing['elevation']} m")
    else:
        st.sidebar.caption("该图纸无直接标高，可点击「同标高图纸」查看")

    if drawing.get("elevation"):
        same_elev = list_drawings_by_elevation(drawing["elevation"])
        if len(same_elev) > 1:
            st.sidebar.markdown("**同标高图纸**")
            for d in same_elev[:6]:
                if d["drawing_id"] == drawing_id:
                    continue
                label = f"{d['file_name'][:28]} [{d['tag_count']}位号]"
                if st.sidebar.button(label, key=f"elev_{d['drawing_id']}"):
                    _set_query_param("drawing_id", d["drawing_id"])
                    st.rerun()
                    return

    map_data = get_map_data(drawing_id)
    if not map_data.get("found"):
        st.error(f"无法加载地图：{map_data.get('reason', '未知原因')}")
        return

    # ── 中间地图 + 右侧档案 ──
    col_map, col_profile = st.columns([3, 1])

    with col_map:
        st.subheader(map_data["file_name"][:60])
        html = render_map_html(map_data)
        components.html(html, height=map_data["sidecar"]["img_h"] + 20, scrolling=True)
        st.caption(f"位号数量：{map_data['tag_count']} | 点击红色热区查看设备档案")

    with col_profile:
        selected_tag = st.session_state.get("map_selected_tag")
        if selected_tag:
            st.subheader(f"设备档案：{selected_tag}")
            if st.button("← 关闭"):
                _clear_tag()
                st.rerun()

            profile = get_device_profile(selected_tag)
            if not profile.get("found"):
                st.warning("未找到设备档案")
                return

            st.markdown(f"**名称：** {profile['name']}")
            st.markdown(f"**类别：** {profile['category'] or '-'}")
            st.markdown(f"**子系统：** {profile['subsystem_no'] or '-'}")
            st.markdown(f"**跨图数：** {profile['drawing_count']} 张图 / {profile['occurrence_count']} 个标注点")

            occ = next((o for o in profile["occurrences"] if o["drawing_id"] == drawing_id), None)
            if occ:
                st.markdown(f"**当前图坐标：** ({occ['x']:.0f}, {occ['y']:.0f})")
                if occ.get("elevation"):
                    st.markdown(f"**标高：** {occ['elevation']['datum_elevation']} m")

            if profile["packing_lists"]:
                st.markdown("---")
                st.markdown("**箱单/供应商候选**")
                seen = set()
                for p in profile["packing_lists"][:10]:
                    key = (p["packing_no"], p["vendor"], p["equip_name"])
                    if key in seen:
                        continue
                    seen.add(key)
                    status_icon = "🟠" if p["status"] == "pending" else "🟢"
                    st.markdown(f"{status_icon} `{p['packing_no']}`")
                    st.markdown(f"&nbsp;&nbsp;{p['vendor'][:16]} | {p['equip_name'][:20]}")

            if profile["pending_confirmations"]:
                st.info(f"有 {profile['pending_confirmations']} 条候选关系待确认，请到「数据校核」页处理。")
        else:
            st.info("点击地图上的红色热区查看设备档案、箱单与供应商信息。")
