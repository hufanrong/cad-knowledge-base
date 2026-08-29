# -*- coding: utf-8 -*-
"""批量导入全部类型文件（CAD + PDF/Word/Excel），带断点续跑与失败记录。

用法：
    python scripts/import_all_types.py --root <目录> [--resume]

进度记录: <kb>/Temp/import_all_types_progress.json（已成功文件路径）
失败记录: <kb>/Temp/import_all_types_failed.json
"""
import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.config import get_config
from src.file_manager.importer import import_file, DOC_EXTENSIONS

KB = get_config().kb_root
PROGRESS_FILE = KB / "Temp" / "import_all_types_progress.json"
FAILED_FILE = KB / "Temp" / "import_all_types_failed.json"

EXTENSIONS = {".dwg", ".dxf", ".dwt", ".dws"} | DOC_EXTENSIONS

# 处理顺序：文档类优先（快），CAD 最后（ODA 慢）
ORDER = {".pdf": 0, ".docx": 0, ".doc": 0, ".xlsx": 0, ".xls": 0,
         ".xlsm": 0, ".csv": 0, ".pptx": 0, ".ppt": 0, ".mpp": 0,
         ".dwg": 1, ".dxf": 1, ".dwt": 1, ".dws": 1}


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(p, data, retries=8):
    payload = json.dumps(data, ensure_ascii=False)
    for attempt in range(retries):
        try:
            Path(p).write_text(payload, encoding="utf-8")
            return True
        except Exception:
            if attempt == retries - 1:
                return False
            time.sleep(0.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="待导入根目录")
    ap.add_argument("--resume", action="store_true", help="断点续跑（跳过已成功文件）")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"目录不存在: {root}", file=sys.stderr)
        sys.exit(1)

    done = set(load_json(PROGRESS_FILE, []))
    failed = load_json(FAILED_FILE, [])

    files = [
        f for f in root.rglob("*")
        if f.is_file()
        and not f.name.startswith("~$")
        and f.suffix.lower() in EXTENSIONS
    ]
    files.sort(key=lambda f: (ORDER.get(f.suffix.lower(), 0), f.name))
    print(f"共扫描到 {len(files)} 个可导入文件，已完成 {len(done)} 个")

    stats = Counter()
    t0 = time.time()
    for i, f in enumerate(files, 1):
        key = str(f)
        if args.resume and key in done:
            continue
        try:
            result = import_file(f)
            status = result.get("status") if isinstance(result, dict) else "ok"
            if status == "ok":
                done.add(key)
                stats["ok"] += 1
            elif status == "duplicate":
                done.add(key)  # 已存在也算完成
                stats["duplicate"] += 1
            else:
                failed.append({"path": key, "error": str(result)[:500]})
                stats["failed"] += 1
                save_json(FAILED_FILE, failed)
        except Exception as e:
            failed.append({"path": key, "error": str(e)[:500]})
            stats["failed"] += 1
            save_json(FAILED_FILE, failed)

        save_json(PROGRESS_FILE, sorted(done))
        if i % 20 == 0 or i == len(files):
            el = time.time() - t0
            print(f"[{i}/{len(files)}] 累计: {dict(stats)} 耗时 {el/60:.1f}min")

    print("\n===== 批量导入完成 =====")
    print(f"状态: {dict(stats)}")
    print(f"总耗时: {(time.time()-t0)/60:.1f}min")
    print(f"失败 {len(failed)} 个（见 {FAILED_FILE}）")


if __name__ == "__main__":
    main()
