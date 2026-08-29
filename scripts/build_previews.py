# -*- coding: utf-8 -*-
"""批量生成图纸预览 PNG（线框渲染）+ sidecar bbox。

用法:
    python scripts/build_previews.py --workers 4          # 正式批量（断点续跑）
    python scripts/build_previews.py --workers 4 --limit 10  # 试跑 10 张

产物：
    D:/WorkBuddy/work/data/knowledge_base/Preview/{drawing_id}.png
    D:/WorkBuddy/work/data/knowledge_base/Preview/{drawing_id}.json  (bbox+尺寸，2.5D 热区映射用)
    drawings.thumbnail_path 回写 PNG 路径
"""
import argparse
import json
import sqlite3
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DB = r"D:/WorkBuddy/work/data/knowledge_base/database/cadkb.db"
PREVIEW_DIR = Path(r"D:/WorkBuddy/work/data/knowledge_base/Preview")


def render_one(args):
    """worker：DWG -> DXF -> 线框 PNG。返回结果 dict（不碰 DB）。

    file_path 不存在时回退 archive_path（OriginalFiles 归档）。
    """
    drawing_id, file_path, archive_path = args
    png = PREVIEW_DIR / f"{drawing_id}.png"
    meta = PREVIEW_DIR / f"{drawing_id}.json"
    if png.exists() and meta.exists():
        return {"drawing_id": drawing_id, "status": "skip"}
    src = file_path if Path(file_path or "").exists() else archive_path
    # 无源文件不提前返回：entities 表若已有解析数据，DB 直渲仍可出图

    try:
        from src.parsers.oda_converter import ODAConverter
        from src.gui.thumbnail import render_dxf_wireframe, render_drawing_from_db

        r = None
        if src and Path(src).exists():
            with tempfile.TemporaryDirectory(prefix="cadkb_pv_") as tmp:
                dxf = ODAConverter().convert_dwg_to_dxf(
                    dwg_path=Path(src), output_dir=tmp,
                    output_version="ACAD2018", audit=False)
                if dxf is not None:
                    r = render_dxf_wireframe(dxf, png)
        if r is None:
            # DB 直渲兜底：DWG 被改动/丢失、ODA 转出空 DXF、渲染为空等情况
            r = render_drawing_from_db(drawing_id, png)
            if r is None:
                return {"drawing_id": drawing_id, "status": "render_fail"}
            status = "ok_db"
        else:
            status = "ok"
        meta.write_text(json.dumps({
            "drawing_id": drawing_id,
            "min_x": r["min_x"], "min_y": r["min_y"],
            "max_x": r["max_x"], "max_y": r["max_y"],
            "img_w": r["img_w"], "img_h": r["img_h"],
        }, ensure_ascii=False), encoding="utf-8")
        return {"drawing_id": drawing_id, "status": status, "png": r["png"]}
    except Exception as e:
        return {"drawing_id": drawing_id, "status": f"error:{e}"[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT d.drawing_id, d.file_path, f.archive_path "
        "FROM drawings d LEFT JOIN files f ON f.drawing_id=d.drawing_id AND f.file_type='dwg'"
    ).fetchall()
    con.close()
    if args.limit:
        rows = rows[:args.limit]
    print(f"待处理图纸 {len(rows)} 张, workers={args.workers}", flush=True)

    t0 = time.time()
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(render_one, (did, fp, ap)): did for did, fp, ap in rows}
        done = 0
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            done += 1
            if done % 25 == 0 or done == len(rows):
                ok = sum(1 for x in results if x["status"] in ("ok", "ok_db", "skip"))
                print(f"  进度 {done}/{len(rows)} | 成功 {ok} | 耗时 {time.time()-t0:.0f}s", flush=True)

    # 主进程统一回写 thumbnail_path
    ok_ids = [(r["png"], r["drawing_id"]) for r in results if r["status"] in ("ok", "ok_db")]
    skip_ids = [r["drawing_id"] for r in results if r["status"] == "skip"]
    if ok_ids:
        con = sqlite3.connect(DB)
        con.execute("PRAGMA busy_timeout=60000")
        con.executemany("UPDATE drawings SET thumbnail_path=? WHERE drawing_id=?", ok_ids)
        # skip 的已有 png，若 thumbnail_path 为空也回填
        for did in skip_ids:
            png = PREVIEW_DIR / f"{did}.png"
            con.execute(
                "UPDATE drawings SET thumbnail_path=? WHERE drawing_id=? AND (thumbnail_path IS NULL OR thumbnail_path='')",
                (str(png), did))
        con.commit()
        con.close()

    from collections import Counter
    stat = Counter(r["status"] for r in results)
    print(f"\n完成，总耗时 {time.time()-t0:.0f}s")
    for k, v in stat.most_common():
        print(f"  {k}: {v}")
    fails = [r for r in results if r["status"] not in ("ok", "skip")]
    for r in fails[:10]:
        print("  失败样本:", r)


if __name__ == "__main__":
    main()
