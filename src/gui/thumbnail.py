"""Thumbnail generator — 缩略图生成 (Phase 10).

Renders a preview image of a DXF/DWG using ezdxf's matplotlib backend.
Used by the Streamlit GUI for visual drawing browsing.

The thumbnail is stored under config.thumbnails_dir (default
KnowledgeBase/thumbnails) and the path recorded on the drawing row.

2026-08-23 增加 render_dxf_wireframe()：自绘 LineCollection 线框渲染器。
原因：ezdxf 通用 drawing 管线（MatplotlibBackend/SVGBackend）在大图上
不可用——12 万实体工艺图渲染需 244s 且 SVG 体积达 385MB；自绘线框版
5s/张、PNG 约 0.2MB，并输出 sidecar bbox（供 2.5D 热区坐标映射）。
"""

from __future__ import annotations

from pathlib import Path

import ezdxf

from src.core.config import get_config
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.gui.thumbnail")

_preview_supported: bool | None = None


def is_preview_supported() -> bool:
    """Check whether ezdxf[draw] (matplotlib backend) is available."""
    global _preview_supported
    if _preview_supported is None:
        try:
            import ezdxf.addons.drawing  # noqa: F401
            import matplotlib  # noqa: F401

            _preview_supported = True
        except ImportError:
            _preview_supported = False
    return _preview_supported


def generate_thumbnail(dxf_path: str | Path) -> Path | None:
    """Render a preview PNG of a DXF file.

    Args:
        dxf_path: Path to the DXF (converted DWGs work too).

    Returns:
        Path to the generated PNG, or None on failure.
    """
    path = Path(dxf_path)
    if not path.exists():
        return None
    if not is_preview_supported():
        logger.warning("ezdxf[draw] 不可用，无法生成缩略图")
        return None

    config = get_config()
    config.ensure_directories()
    out = config.thumbnails_dir / (path.stem + ".png")

    try:
        doc = ezdxf.readfile(path)
        msp = doc.modelspace()

        import matplotlib
        matplotlib.use("Agg")
        from ezdxf.addons.drawing import RenderContext, Frontend
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
        import matplotlib.pyplot as plt

        fig = plt.figure(figsize=(6.4, 4.8), dpi=100)
        ax = fig.add_axes([0, 0, 1, 1])
        ctx = RenderContext(doc)
        backend = MatplotlibBackend(ax)
        Frontend(ctx, backend).draw_layout(msp, finalize=True)
        fig.savefig(out, dpi=100)
        plt.close(fig)

        if out.exists() and out.stat().st_size > 0:
            logger.info(f"缩略图已生成: {out.name} ({out.stat().st_size} bytes)")
            return out
    except Exception as e:
        logger.warning(f"缩略图生成失败: {path.name} - {e}")

    return None


def generate_thumbnail_for_drawing(drawing_id: str) -> Path | None:
    """Generate a thumbnail for a drawing stored in the database.

    Looks up the drawing's file path, converts to DXF if needed, then
    renders a preview. Returns the PNG path (also updates the DB row).
    """
    from src.database.connection import get_session
    from src.database.repositories import DrawingRepository

    session = get_session()
    repo = DrawingRepository(session)
    d = repo.find_by_id(drawing_id)
    if not d:
        session.close()
        return None

    file_path = Path(d.file_path)
    session.close()
    if not file_path.exists():
        return None

    # DWG needs conversion first
    if file_path.suffix.lower() == ".dwg":
        from src.parsers.oda_converter import ODAConverter, is_oda_available
        from src.parsers.autocad_com import is_autocad_available, convert_dwg_to_dxf

        if is_oda_available():
            with __import__("tempfile").TemporaryDirectory(prefix="cadkb_thumb_") as tmp:
                dxf = ODAConverter().convert_dwg_to_dxf(
                    dwg_path=file_path, output_dir=tmp,
                    output_version="ACAD2018", audit=False,
                )
                if dxf is None:
                    return None
                thumb = generate_thumbnail(dxf)
        elif is_autocad_available():
            with __import__("tempfile").TemporaryDirectory(prefix="cadkb_thumb_") as tmp:
                dxf = convert_dwg_to_dxf(dwg_path=file_path, output_dir=tmp)
                if dxf is None:
                    return None
                thumb = generate_thumbnail(dxf)
        else:
            return None
    else:
        thumb = generate_thumbnail(file_path)

    if thumb is not None:
        session = get_session()
        repo = DrawingRepository(session)
        repo.update_thumbnail_path(drawing_id, str(thumb))
        session.close()
    return thumb


def render_dxf_wireframe(dxf_path: str | Path, out_png: str | Path,
                         max_width: int = 2400) -> dict | None:
    """自绘线框渲染：DXF → PNG（只画 LINE/LWPOLYLINE/CIRCLE/ARC）。

    实测：12 万实体工艺图 5s、PNG 约 0.2MB；ezdxf 通用管线同图 244s、
    SVG 385MB 不可用。文字/INSERT 不绘制（2.5D 由热区叠加层负责标注）。

    Args:
        dxf_path: DXF 文件路径。
        out_png: 输出 PNG 路径。
        max_width: 输出图片最大宽度（像素），高度按比例（上限 4000）。

    Returns:
        {png, min_x, min_y, max_x, max_y, img_w, img_h} 或 None（失败）。
        bbox 用于图纸坐标 → 像素坐标的热区映射。
    """
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    try:
        # recover 模式容错：ODA 对部分 DWG 转出的 DXF 缺 ENDSEC 等标签，
        # 严格 readfile 会抛 DXFStructureError；recover 可正常解析
        from ezdxf.recover import readfile as recover_readfile
        doc, _auditor = recover_readfile(dxf_path)
        msp = doc.modelspace()

        segs = []

        def _collect(e, depth=0):
            """收集线框段；INSERT 块引用递归展开（电气图几乎全是块引用）。"""
            t = e.dxftype()
            try:
                if t == "INSERT":
                    if depth < 3:
                        for ve in e.virtual_entities():
                            _collect(ve, depth + 1)
                elif t == "LINE":
                    s, en = e.dxf.start, e.dxf.end
                    segs.append([(s.x, s.y), (en.x, en.y)])
                elif t == "LWPOLYLINE":
                    pts = [(p[0], p[1]) for p in e.get_points()]
                    if len(pts) >= 2:
                        if e.closed:
                            pts.append(pts[0])
                        segs.append(pts)
                elif t == "CIRCLE":
                    c, r = e.dxf.center, e.dxf.radius
                    th = np.linspace(0, 2 * np.pi, 48)
                    segs.append([(c.x + r * np.cos(a), c.y + r * np.sin(a)) for a in th])
                elif t == "ARC":
                    c, r = e.dxf.center, e.dxf.radius
                    th = np.linspace(np.radians(e.dxf.start_angle),
                                     np.radians(e.dxf.end_angle), 32)
                    segs.append([(c.x + r * np.cos(a), c.y + r * np.sin(a)) for a in th])
            except Exception:
                pass

        for e in msp:
            _collect(e)
        if not segs:
            return None

        allpts = np.concatenate([np.array(s) for s in segs])
        minx, miny = allpts.min(axis=0)
        maxx, maxy = allpts.max(axis=0)
        spanx = max(maxx - minx, 1e-6)
        spany = max(maxy - miny, 1e-6)
        W = max_width
        # 高度下限保护：极端细长图（如单列电力图）防止 H=0 导致 savefig 空图报错
        H = min(max(int(W * spany / spanx), 200), 4000)

        fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_axis_off()
        ax.add_collection(LineCollection(segs, linewidths=0.3, colors="#222222"))
        ax.set_xlim(minx, maxx)
        ax.set_ylim(miny, maxy)
        out = Path(out_png)
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=100)
        plt.close(fig)

        if out.exists() and out.stat().st_size > 0:
            return {"png": str(out), "min_x": float(minx), "min_y": float(miny),
                    "max_x": float(maxx), "max_y": float(maxy),
                    "img_w": W, "img_h": H}
    except Exception as e:
        logger.warning(f"线框渲染失败: {Path(dxf_path).name} - {e}")
    return None


def render_drawing_from_db(drawing_id: str, out_png: str | Path,
                           max_width: int = 2400) -> dict | None:
    """从 entities 表直渲线框 PNG（不依赖 DWG 原文件）。

    背景：部分 DWG 在入库解析后被外部脚本改动，ODA 再转换转出空 DXF；
    也有原文件被移动的情况。entities 表已存全部几何（coordinates/
    properties/bbox），可直接渲染，且与解析数据同源、无 ODA/ezdxf 开销。

    绘制：LINE/LWPOLYLINE（coordinates）+ CIRCLE/ARC（properties）；
    INSERT 块不展开（第一版，仅占位意义不大故跳过）。
    """
    import json
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    from src.database.connection import get_session
    from sqlalchemy import text as _t

    session = get_session()
    try:
        rows = session.execute(_t(
            "SELECT entity_type, coordinates, properties FROM entities "
            "WHERE drawing_id=:did AND entity_type IN ('LINE','LWPOLYLINE','CIRCLE','ARC')"
        ), {"did": drawing_id}).fetchall()
    finally:
        session.close()
    if not rows:
        return None

    segs = []
    for etype, coords, props in rows:
        try:
            if etype == "LINE":
                c = json.loads(coords)
                segs.append([(c[0], c[1]), (c[3], c[4])])
            elif etype == "LWPOLYLINE":
                c = json.loads(coords)
                pts = [(c[i], c[i + 1]) for i in range(0, len(c) - 2, 3)]
                if len(pts) >= 2:
                    segs.append(pts)
            elif etype in ("CIRCLE", "ARC"):
                p = json.loads(props)
                center, r = p.get("center"), p.get("radius")
                if not center or not r:
                    continue
                if etype == "CIRCLE":
                    th = np.linspace(0, 2 * np.pi, 48)
                else:
                    th = np.linspace(np.radians(p.get("start_angle", 0)),
                                     np.radians(p.get("end_angle", 360)), 32)
                segs.append([(center[0] + r * np.cos(a), center[1] + r * np.sin(a)) for a in th])
        except Exception:
            continue
    if not segs:
        return None

    allpts = np.concatenate([np.array(s) for s in segs])
    minx, miny = allpts.min(axis=0)
    maxx, maxy = allpts.max(axis=0)
    spanx = max(maxx - minx, 1e-6)
    spany = max(maxy - miny, 1e-6)
    W = max_width
    H = min(max(int(W * spany / spanx), 200), 4000)

    try:
        fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_axis_off()
        ax.add_collection(LineCollection(segs, linewidths=0.3, colors="#222222"))
        ax.set_xlim(minx, maxx)
        ax.set_ylim(miny, maxy)
        out = Path(out_png)
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=100)
        plt.close(fig)
    except Exception as e:
        logger.warning(f"DB直渲保存失败: {drawing_id[:8]} - {e}")
        return None

    if out.exists() and out.stat().st_size > 0:
        return {"png": str(out), "min_x": float(minx), "min_y": float(miny),
                "max_x": float(maxx), "max_y": float(maxy),
                "img_w": W, "img_h": H}
    return None
