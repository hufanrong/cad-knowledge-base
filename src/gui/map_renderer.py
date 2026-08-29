"""2.5D 地图热区渲染器（阶段 4 + 阶段 5 增强）。

输入：map_service.get_map_data() 返回的地图数据。
输出：可嵌入 Streamlit components.v1.html 的 HTML 片段。

坐标映射：
- 图纸坐标 (x, y) → 像素坐标 (px, py)
- px = (x - min_x) / (max_x - min_x) * img_w
- py = (max_y - y) / (max_y - min_y) * img_h   # Y 轴翻转

阶段 5 增强：
- 悬浮 tooltip 显示位号、供应商、箱单号、设备名称
- 热区颜色：有已确认箱单=绿色，候选箱单=橙色，无箱单=红色
- 大图限制最大显示宽度，支持横向滚动
"""

from __future__ import annotations

import json
from typing import Any


def _to_px(x: float, y: float, sidecar: dict) -> tuple[float, float]:
    """图纸坐标 → 像素坐标。"""
    min_x = sidecar["min_x"]
    min_y = sidecar["min_y"]
    max_x = sidecar["max_x"]
    max_y = sidecar["max_y"]
    img_w = sidecar["img_w"]
    img_h = sidecar["img_h"]

    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)

    px = (x - min_x) / span_x * img_w
    py = (max_y - y) / span_y * img_h
    return px, py


def _hotspot_size(height: float, sidecar: dict) -> float:
    """根据文字高度估算热区半径（像素）。"""
    min_x = sidecar["min_x"]
    max_x = sidecar["max_x"]
    img_w = sidecar["img_w"]
    span_x = max(max_x - min_x, 1e-6)
    px_h = abs(height) / span_x * img_w if height else 12
    return max(min(px_h * 2.5, 24), 10)


def _status_color(pack_status: str | None, has_packing: bool) -> tuple[str, str]:
    """根据箱单候选状态返回热区颜色和边框颜色。"""
    if pack_status == "confirmed":
        return "rgba(40, 167, 69, 0.40)", "rgba(25, 135, 84, 0.90)"  # 绿
    if has_packing:
        return "rgba(255, 140, 0, 0.40)", "rgba(255, 100, 0, 0.90)"  # 橙（候选）
    return "rgba(255, 60, 60, 0.35)", "rgba(255, 30, 30, 0.85)"      # 红（无）


def render_map_html(map_data: dict[str, Any], max_display_width: int = 1600) -> str:
    """生成地图 HTML。"""
    if not map_data.get("found"):
        return "<div style='padding:20px'>地图数据不可用</div>"

    drawing_id = map_data["drawing_id"]
    preview_url = map_data["preview_url"]
    sidecar = map_data["sidecar"]
    img_w = sidecar["img_w"]
    img_h = sidecar["img_h"]
    tags = map_data["tags"]

    # file:// 协议给浏览器显示本地 PNG（Windows 路径 D:/ → /D:/）
    preview_url = preview_url.replace("D:/", "/D:/")

    # 显示宽度限制（阶段 5：大图分块/滚动）
    display_w = min(img_w, max_display_width)
    scale = display_w / img_w

    hotspots = []
    seen = set()
    for t in tags:
        tag = t["tag_no"]
        if tag in seen:
            continue
        seen.add(tag)
        x, y = t["x"], t["y"]
        if x is None or y is None:
            continue
        px, py = _to_px(x, y, sidecar)
        r = _hotspot_size(t.get("height", 2.0), sidecar)
        if not (-r <= px <= img_w + r and -r <= py <= img_h + r):
            continue

        has_packing = bool(t.get("packing_no"))
        fill, stroke = _status_color(t.get("pack_status"), has_packing)
        tooltip = tag
        if t.get("equip_name"):
            tooltip += f"\\n设备：{t['equip_name'][:20]}"
        if t.get("vendor"):
            tooltip += f"\\n厂家：{t['vendor'][:16]}"
        if t.get("packing_no"):
            tooltip += f"\\n箱单：{t['packing_no']}"
            if t.get("pack_status") == "pending":
                tooltip += "（待确认）"

        hotspots.append({
            "tag": tag,
            "px": px,
            "py": py,
            "r": r,
            "fill": fill,
            "stroke": stroke,
            "tooltip": tooltip,
        })

    hotspots_js = json.dumps(hotspots, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
.map-wrapper {{
  overflow: hidden;
  max-width: 100%;
  border: 1px solid #ddd;
  background: #f8f8f8;
  position: relative;
}}
.map-container {{
  position: absolute;
  top: 0;
  left: 0;
  display: inline-block;
  width: {img_w}px;
  height: {img_h}px;
  transform-origin: top left;
  cursor: grab;
}}
.map-container:active {{
  cursor: grabbing;
}}
.controls {{
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 100;
  background: rgba(255,255,255,0.9);
  border: 1px solid #ccc;
  border-radius: 4px;
  padding: 4px;
}}
.controls button {{
  margin: 0 2px;
  padding: 4px 8px;
  font-size: 12px;
  cursor: pointer;
}}
.map-bg {{
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}}
.hotspot {{
  position: absolute;
  border-radius: 50%;
  cursor: pointer;
  transform: translate(-50%, -50%);
  transition: transform 0.15s, opacity 0.15s;
  z-index: 10;
}}
.hotspot:hover {{
  transform: translate(-50%, -50%) scale(1.35);
  z-index: 20;
}}
.hotspot::after {{
  content: attr(data-tip);
  position: absolute;
  left: 50%;
  top: -32px;
  transform: translateX(-50%);
  background: rgba(0,0,0,0.85);
  color: #fff;
  padding: 5px 10px;
  border-radius: 4px;
  font-size: 11px;
  line-height: 1.4;
  white-space: pre;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.15s;
  max-width: 220px;
  text-align: left;
}}
.hotspot:hover::after {{
  opacity: 1;
}}
.legend {{
  margin: 6px 0;
  font-size: 12px;
  color: #333;
}}
.dot {{
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-right: 4px;
  vertical-align: middle;
}}
</style>
</head>
<body>
<div class="legend">
  <span class="dot" style="background:rgba(255,60,60,0.7);border:1px solid rgba(255,30,30,0.9)"></span>无箱单
  <span class="dot" style="background:rgba(255,140,0,0.7);border:1px solid rgba(255,100,0,0.9)"></span>箱单候选
  <span class="dot" style="background:rgba(40,167,69,0.7);border:1px solid rgba(25,135,84,0.9)"></span>已确认箱单
</div>
<div class="controls">
  <button id="btnZoomIn" title="放大">+</button>
  <button id="btnZoomOut" title="缩小">−</button>
  <button id="btnReset" title="重置">⟲</button>
  <button id="btnToggle" title="显示/隐藏热区">热区</button>
</div>
<div class="map-wrapper" id="mapWrapper">
  <div class="map-container" id="mapContainer">
    <img class="map-bg" src="file://{preview_url}" alt="底图">
  </div>
</div>
<script>
const hotspots = {hotspots_js};
const drawingId = "{drawing_id}";
const container = document.getElementById("mapContainer");
const wrapper = document.getElementById("mapWrapper");

let scale = 1;
let panX = 0, panY = 0;
let dragging = false;
let startX = 0, startY = 0;
let hotspotsVisible = true;

function applyTransform() {{
  container.style.transform = `translate(${{panX}}px, ${{panY}}px) scale(${{scale}})`;
}}

function fit() {{
  const parentW = wrapper.parentElement ? wrapper.parentElement.clientWidth : wrapper.clientWidth;
  scale = Math.min(1, parentW / {img_w});
  panX = 0; panY = 0;
  applyTransform();
  wrapper.style.height = ({img_h} * scale) + "px";
}}

window.addEventListener("resize", fit);
fit();

const hotspotEls = [];
hotspots.forEach(h => {{
  const el = document.createElement("div");
  el.className = "hotspot";
  el.setAttribute("data-tip", h.tooltip);
  el.style.left = h.px + "px";
  el.style.top = h.py + "px";
  el.style.width = (h.r * 2) + "px";
  el.style.height = (h.r * 2) + "px";
  el.style.backgroundColor = h.fill;
  el.style.border = "1.5px solid " + h.stroke;
  el.addEventListener("click", (e) => {{
    e.stopPropagation();
    const url = new URL(window.parent.location.href);
    url.searchParams.set("page", "map");
    url.searchParams.set("drawing_id", drawingId);
    url.searchParams.set("tag", h.tag);
    window.parent.location.href = url.toString();
  }});
  container.appendChild(el);
  hotspotEls.push(el);
}});

document.getElementById("btnZoomIn").addEventListener("click", () => {{ scale *= 1.2; applyTransform(); wrapper.style.height = ({img_h} * scale) + "px"; }});
document.getElementById("btnZoomOut").addEventListener("click", () => {{ scale /= 1.2; applyTransform(); wrapper.style.height = ({img_h} * scale) + "px"; }});
document.getElementById("btnReset").addEventListener("click", fit);
document.getElementById("btnToggle").addEventListener("click", () => {{
  hotspotsVisible = !hotspotsVisible;
  hotspotEls.forEach(el => el.style.display = hotspotsVisible ? "block" : "none");
}});

// 拖拽平移
wrapper.addEventListener("mousedown", (e) => {{ dragging = true; startX = e.clientX - panX; startY = e.clientY - panY; }});
window.addEventListener("mousemove", (e) => {{
  if (!dragging) return;
  panX = e.clientX - startX;
  panY = e.clientY - startY;
  applyTransform();
}});
window.addEventListener("mouseup", () => {{ dragging = false; }});
</script>
</body>
</html>"""
    return html
