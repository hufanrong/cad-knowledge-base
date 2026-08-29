"""轴网定位 v2: ASCII 轴号 + 轴距校验 + FC0203DC01 映射到结构图.

Mapping strategy (per-axis, independent x/y):
1. Extract axis coordinates + ASCII axis labels for both drawings
2. Common labels -> coordinate pairs; verify spacing consistency
3. For a point in 工艺图: find nearest vertical axis (x) and nearest
   horizontal axis (y); map each via the corresponding structure axis
4. Output the mapped structure-coordinate region
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.database.connection import get_session, init_database  # noqa: E402
from src.database.models import DrawingModel, EntityModel, TextModel  # noqa: E402

MIN_AXIS_LEN = 5000
CLUSTER_TOL = 300
AXIS_ANGLE_TOL = 0.02
ASCII_OK = re.compile(r"^[A-Za-z0-9]$")

FC_ANCHORS = [(149533.6, -697579.7), (831270.2, -705832.3)]


def _lines(drawing_id: str):
    session = get_session()
    try:
        rows = (
            session.query(EntityModel)
            .filter(EntityModel.drawing_id == drawing_id,
                    EntityModel.entity_type == "LINE")
            .limit(80000)
            .all()
        )
    finally:
        session.close()
    out = []
    for e in rows:
        try:
            c = json.loads(e.coordinates) if isinstance(e.coordinates, str) else e.coordinates
            if len(c) < 6:
                continue
            p1, p2 = (c[0], c[1]), (c[3], c[4])
            dx, dy = p2[0] - p1[0], p2[1] - p1[1]
            L = math.hypot(dx, dy)
            if L < MIN_AXIS_LEN:
                continue
            out.append((p1, p2, L, dx, dy))
        except Exception:
            pass
    return out


def _texts(drawing_id: str):
    session = get_session()
    try:
        rows = (
            session.query(TextModel)
            .filter(TextModel.drawing_id == drawing_id)
            .all()
        )
    finally:
        session.close()
    out = []
    for t in rows:
        c = t.text_content.strip()
        if not c or not ASCII_OK.match(c):
            continue
        try:
            p = eval(t.position) if isinstance(t.position, str) else t.position
            out.append((c, p[0], p[1]))
        except Exception:
            pass
    return out


def _cluster(offsets):
    offsets.sort()
    clusters = []
    for o in offsets:
        if clusters and abs(o - clusters[-1][-1]) <= CLUSTER_TOL:
            clusters[-1].append(o)
        else:
            clusters.append([o])
    return [sum(c) / len(c) for c in clusters if len(c) >= 1]


def _axes(lines):
    h_off, v_off = [], []
    for p1, p2, L, dx, dy in lines:
        if abs(dy) / L > (1 - AXIS_ANGLE_TOL):
            h_off.append((p1[1] + p2[1]) / 2)   # 水平轴 -> y 常数
        if abs(dx) / L > (1 - AXIS_ANGLE_TOL):
            v_off.append((p1[0] + p2[0]) / 2)   # 垂直轴 -> x 常数
    return _cluster(h_off), _cluster(v_off)


def _label(axis_coords, vertical, texts, dist=4000):
    labels = {}
    for c in axis_coords:
        best, bd = None, 1e18
        for txt, x, y in texts:
            if vertical:
                d = abs(x - c)
            else:
                d = abs(y - c)
            if d < dist and d < bd:
                bd, best = d, txt
        if best:
            labels.setdefault(best, c)
    return labels


def build(drawing_name: str):
    session = get_session()
    d = session.query(DrawingModel).filter(
        DrawingModel.file_name == drawing_name).first()
    session.close()
    if not d:
        return None
    lines = _lines(d.drawing_id)
    texts = _texts(d.drawing_id)
    h_axes, v_axes = _axes(lines)
    return {
        "name": drawing_name[:40],
        "h_labels": _label(h_axes, False, texts),
        "v_labels": _label(v_axes, True, texts),
    }


def map_point(pt, src, dst):
    """Map (x,y) from src drawing to dst drawing via shared axis labels."""
    x, y = pt
    # X: find nearest vertical axis in src, map through common label
    sx_v = src["v_labels"]
    dx_v = dst["v_labels"]
    nx = None
    if sx_v and dx_v:
        common = set(sx_v) & set(dx_v)
        if common:
            # nearest src vertical axis by x
            best, bx = None, None
            for lbl, vx in sx_v.items():
                if lbl in common and (best is None or abs(vx - x) < best):
                    best, bx = abs(vx - x), (vx, lbl)
            if bx:
                # map via that axis + axis spacing from neighbors
                lbl = bx[1]
                src_x = sx_v[lbl]
                dst_x = dx_v[lbl]
                # scale by nearest neighbor axis pair
                others = [l for l in common if l != lbl]
                scale = 1.0
                if others:
                    # use distance to nearest other common axis for scale
                    src_other = min(others, key=lambda l: abs(sx_v[l] - src_x))
                    ds = abs(sx_v[src_other] - src_x)
                    dd = abs(dx_v[src_other] - dst_x)
                    if ds > 1e-6:
                        scale = dd / ds
                nx = dst_x + (x - src_x) * scale
    # Y: nearest horizontal axis
    sy_h = src["h_labels"]
    dy_h = dst["h_labels"]
    ny = None
    if sy_h and dy_h:
        common = set(sy_h) & set(dy_h)
        if common:
            best, by = None, None
            for lbl, hy in sy_h.items():
                if lbl in common and (best is None or abs(hy - y) < best):
                    best, by = abs(hy - y), (hy, lbl)
            if by:
                lbl = by[1]
                src_y = sy_h[lbl]
                dst_y = dy_h[lbl]
                others = [l for l in common if l != lbl]
                scale = 1.0
                if others:
                    src_other = min(others, key=lambda l: abs(sy_h[l] - src_y))
                    ds = abs(sy_h[src_other] - src_y)
                    dd = abs(dy_h[src_other] - dst_y)
                    if ds > 1e-6:
                        scale = dd / ds
                ny = dst_y + (y - src_y) * scale
    return nx, ny


if __name__ == "__main__":
    init_database()
    proc = build("0203 回转窑头装置工艺图（2025.05.07）-R0.dwg")
    struc = build("0203 回转窑头装置-结构图（2025.07.15）-R0.dwg")
    if not proc or not struc:
        print("缺图")
        sys.exit(1)

    print("工艺图 垂直轴号:", dict(sorted(proc["v_labels"].items())))
    print("工艺图 水平轴号:", dict(sorted(proc["h_labels"].items())))
    print("结构图 垂直轴号:", dict(sorted(struc["v_labels"].items())))
    print("结构图 水平轴号:", dict(sorted(struc["h_labels"].items())))
    print()
    print("公共轴号 垂直:", sorted(set(proc["v_labels"]) & set(struc["v_labels"])))
    print("公共轴号 水平:", sorted(set(proc["h_labels"]) & set(struc["h_labels"])))
    print()

    for pt in FC_ANCHORS:
        nx, ny = map_point(pt, proc, struc)
        if nx is None or ny is None:
            print(f"FC({pt[0]:.0f},{pt[1]:.0f}) -> 映射失败（公共轴不足）")
        else:
            print(f"FC({pt[0]:.0f},{pt[1]:.0f}) -> 结构图({nx:.0f},{ny:.0f})")
