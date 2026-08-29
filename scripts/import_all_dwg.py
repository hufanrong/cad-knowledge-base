"""批量导入全部剩余 DWG（01/03/04/05/06 系统）。

用法：
    python scripts/import_all_dwg.py [--dir 系统目录] [--resume]
支持断点续跑：进度记录在 <kb>/Temp/dwg_import_progress.json，失败文件单独记录。
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config import get_config
from src.database.connection import get_session, init_database
from src.database.models import FileModel
from src.file_manager.hasher import compute_sha256
from src.file_manager.importer import import_file

KB = get_config().kb_root
PROGRESS_FILE = KB / "Temp" / "dwg_import_progress.json"
FAILED_FILE = KB / "Temp" / "dwg_import_failed.json"

ROOT = Path("D:/Users/hufanrong/Desktop/Manono施工图图纸2025.12.5-选冶/设计图纸/冶炼厂/0冶炼厂图纸")
SYSTEM_DIRS = ["01原辅料系统", "03湿法系统", "04硫磺制酸", "05公辅系统", "06厂前区"]


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(p, data, retries=8):
    """写入 JSON 进度，带重试（避免 Windows 瞬时文件锁导致崩溃）。"""
    payload = json.dumps(data, ensure_ascii=False)
    for attempt in range(retries):
        try:
            Path(p).write_text(payload, encoding="utf-8")
            return True
        except PermissionError:
            if attempt == retries - 1:
                print(f"[警告] 写入失败(已重试{retries}次): {p}", flush=True)
                return False
            time.sleep(1.5)
    return False


def main():
    init_database()
    s = get_session()
    imported_hashes = {r.sha256 for r in s.query(FileModel.sha256).all()}
    s.close()

    # 1. Collect all DWG not yet imported
    all_new = []
    for d in SYSTEM_DIRS:
        base = ROOT / d
        if not base.exists():
            print(f"跳过（不存在）: {d}")
            continue
        for f in base.rglob("*.dwg"):
            if not f.is_file():
                continue
            try:
                if compute_sha256(f) not in imported_hashes:
                    all_new.append(f)
            except Exception:
                pass
    print(f"待导入 DWG: {len(all_new)}", flush=True)

    # 2. Resume support
    done = set(load_json(PROGRESS_FILE, []))
    failed = load_json(FAILED_FILE, [])
    pending = [f for f in all_new if str(f) not in done]
    print(f"已完成: {len(done)} | 本次执行: {len(pending)}", flush=True)

    results = []
    t0 = time.time()
    for i, f in enumerate(pending, 1):
        try:
            r = import_file(f)
            results.append({"path": str(f), "status": r.get("status"), "parse": r.get("parse_status")})
            if r.get("status") == "error":
                failed.append({"path": str(f), "message": r.get("message", "")})
                save_json(FAILED_FILE, failed)
        except Exception as e:
            results.append({"path": str(f), "status": "error", "parse": ""})
            failed.append({"path": str(f), "message": str(e)})
            save_json(FAILED_FILE, failed)
        done.add(str(f))
        if i % 2 == 0 or i == len(pending):
            save_json(PROGRESS_FILE, list(done))
            el = time.time() - t0
            rate = el / i
            remain = rate * (len(pending) - i)
            print(f"  进度 {i}/{len(pending)} 耗时{el/60:.0f}min 预计剩余{remain/60:.0f}min", flush=True)

    save_json(PROGRESS_FILE, list(done))
    st = Counter(r["status"] for r in results)
    ps = Counter(r.get("parse", "") for r in results)
    print("=== DWG 批量导入完成 ===", flush=True)
    print(f"状态: {dict(st)}", flush=True)
    print(f"解析: {dict(ps)}", flush=True)
    print(f"总耗时: {(time.time()-t0)/60:.0f}min | 失败 {len(failed)} 个（见 dwg_import_failed.json）", flush=True)


if __name__ == "__main__":
    main()
