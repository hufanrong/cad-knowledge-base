"""Lightweight 图纸定位图: plot text positions + mark FC0203DC01.

Fast alternative to full rendering — shows where the device sits in the
drawing (which quadrant/region) using TEXT entity positions, so the user
can correlate with the structure drawing region.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.database.connection import get_session, init_database  # noqa: E402
from src.database.models import DrawingModel, TextModel  # noqa: E402

FC_ANCHORS = [(149533.6, -697579.7), (831270.2, -705832.3)]


def plot_positions(
    drawing_name: str,
    anchors: list[tuple[float, float]],
    out_png: str,
    label: str = "FC0203DC01",
    near_text: int = 6,
) -> Path | None:
    init_database()
    session = get_session()
    d = (
        session.query(DrawingModel)
        .filter(DrawingModel.file_name == drawing_name)
        .first()
    )
    if not d:
        session.close()
        return None
    texts = (
        session.query(TextModel)
        .filter(TextModel.drawing_id == d.drawing_id)
        .all()
    )
    session.close()

    pts = []
    for t in texts:
        c = t.text_content.strip()
        if not c:
            continue
        try:
            p = eval(t.position) if isinstance(t.position, str) else t.position
            pts.append((p[0], p[1], c[:20]))
        except Exception:
            pass

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(14, 10), dpi=110)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    ax.scatter(xs, ys, s=3, c="steelblue", alpha=0.45,
               label=f"图纸文字 ({len(pts)})")

    for x, y in anchors:
        ax.plot(x, y, "o", markersize=14, mfc="none", mec="red",
                mew=3, zorder=10)
        ax.annotate(label, (x, y), xytext=(10, 10),
                    textcoords="offset points", color="red",
                    fontsize=15, fontweight="bold", zorder=11,
                    bbox=dict(boxstyle="round,pad=0.3", fc="white",
                              ec="red", alpha=0.92))
        # nearest text labels
        near = sorted(pts, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)
        for p in near[:near_text]:
            ax.annotate(p[2], (p[0], p[1]), xytext=(4, 4),
                        textcoords="offset points", fontsize=7,
                        color="green", alpha=0.85)

    ax.set_title(f"{drawing_name[:45]} — {label} 定位", fontsize=13)
    ax.set_xlabel("X (mm)"); ax.set_ylabel("Y (mm)")
    ax.legend(loc="upper right")
    ax.set_aspect("equal", adjustable="box")
    fig.tight_layout()
    fig.savefig(out_png)
    plt.close(fig)
    return Path(out_png)


if __name__ == "__main__":
    out = plot_positions(
        "0203 回转窑头装置工艺图（2025.05.07）-R0.dwg",
        FC_ANCHORS,
        "D:/WorkBuddy/work/data/knowledge_base/Preview/"
        "FC0203DC01_工艺图定位.png",
    )
    print(f"OUT: {out}")
