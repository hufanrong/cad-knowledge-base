# -*- coding: utf-8 -*-
"""资料库入口监听器 — 监控桌面「资料库入口」目录，自动导入新文件到知识库。

流程：
  1. 监测到新文件（写入稳定后）→ 调用 import_file 解析入库（去重/归档/向量化/项目推断自动完成）
  2. 导入成功 → 原文件移入 入口/_已处理/<日期>/
  3. 导入失败 → 原文件移入 入口/_失败/<日期>/（保留现场，日志记录原因）
  4. 每批处理完毕 → 重建 belongs_to_subsystem 关联（与既有图纸建立联系）

用法：
  python scripts/watch_entry.py                 # 前台运行
  pythonw scripts/watch_entry.py                # 后台运行（无窗口）

日志：<kb>/Temp/watch_entry.log
"""
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.config import get_config
from src.file_manager.importer import import_file, DOC_EXTENSIONS
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.watch_entry")

CAD_EXTENSIONS = {".dwg", ".dxf", ".dwt", ".dws"}
IMPORTABLE = CAD_EXTENSIONS | DOC_EXTENSIONS

# 程序源码扩展名黑名单：zip 解压/入口扫描时直接跳过，不导入
# （2026-08-22 新增：历史曾因 zip 解压出大量 .mc/.cpp 源码拖垮监听队列）
# （2026-08-29 新增 .bak/.dwl/.dwl2：CAD 备份与锁文件，ODA 转换会超时卡死并致监听进程崩溃）
SKIP_EXTENSIONS = {
    ".mc", ".mct", ".cpp", ".h", ".hpp", ".c", ".cc", ".cs",
    ".py", ".js", ".ts", ".java", ".asm", ".s", ".lsp", ".scr",
    ".txt", ".log", ".ini", ".cfg", ".json", ".xml",
    ".bak", ".dwl", ".dwl2",
}

# 监听入口目录：可用环境变量 CADKB_ENTRY_DIR 覆盖（每工程独立入口），默认桌面共享入口
ENTRY = Path(os.environ.get("CADKB_ENTRY_DIR", r"D:\Users\hufanrong\Desktop\资料库入口"))

# 2026-08-31 新增：导入后原始文件直接送入回收中转站（老板定案——原件不再保留，
# 只保留 cadkb.db 中的解析产物 + 导入记录表）
#   CADKB_RECYCLE_ORIGINAL=0 可退回旧行为（移入 入口/_已处理、_失败）
RECYCLE_ORIGINAL = os.environ.get("CADKB_RECYCLE_ORIGINAL", "1") != "0"
RECYCLE_DIR = Path(
    os.environ.get(
        "CADKB_RECYCLE_DIR",
        r"D:\Users\hufanrong\Desktop\回收中转站",
    )
)

# 子目录隔离：这些目录不参与扫描
SKIP_DIRS = {"_已处理", "_失败", "_待处理"}

# 文件稳定判定：连续两次扫描 size/mtime 一致才算写完
STABLE_SECONDS = 3.0
STABLE_CHECKS = 2

# 处理超时（单文件，CAD 走 ODA 可能较慢）
PROCESS_TIMEOUT = 600

# 重复即跳过开关（2026-08-29 新增）：
#   CADKB_SKIP_DUPLICATE=1（默认）: import 前按 SHA256 预查重，命中知识库已有内容直接归档，
#     跳过解析/向量化（文档类重复原逻辑仍会重新解析，本开关可大幅提速全量导入）
#   CADKB_SKIP_DUPLICATE=0: 关闭预查重，走原有流程
SKIP_DUPLICATE = os.environ.get("CADKB_SKIP_DUPLICATE", "1") != "0"


def _precheck_duplicate(p: Path) -> dict | None:
    """只读预查重：按 SHA256 查知识库 files/drawings 表，命中返回重复信息，否则 None。

    失败不阻塞（返回 None 走正常导入）。无副作用（不登记来源、不复制归档）。
    """
    import hashlib
    import sqlite3

    try:
        from src.core.config import get_config

        h = hashlib.sha256(p.read_bytes()).hexdigest()
        con = sqlite3.connect(get_config().db_path)
        try:
            row = con.execute(
                "SELECT file_id, original_name FROM files WHERE sha256 = ?", (h,)
            ).fetchone()
            if row:
                return {"status": "duplicate", "file_id": row[0], "file_name": row[1]}
            row = con.execute(
                "SELECT drawing_id, file_name FROM drawings WHERE file_hash = ?", (h,)
            ).fetchone()
            if row:
                return {"status": "duplicate", "file_id": row[0], "file_name": row[1]}
        finally:
            con.close()
    except Exception as e:
        logger.warning(f"预查重失败（继续正常导入）: {p.name}: {e}")
    return None


def wait_stable(p: Path, timeout: float = 30.0) -> bool:
    """等待文件写入完成（拷贝中的文件 size 会变化）。"""
    t0 = time.time()
    last = None
    stable = 0
    while time.time() - t0 < timeout:
        try:
            st = p.stat()
            sig = (st.st_size, st.st_mtime_ns)
            if sig == last:
                stable += 1
                if stable >= STABLE_CHECKS:
                    time.sleep(0.2)
                    return True
            else:
                stable = 0
            last = sig
        except FileNotFoundError:
            return False
        time.sleep(STABLE_SECONDS)
    return False


def process_file(p: Path, done_dir: Path, failed_dir: Path) -> dict:
    """处理单个文件。zip 先解压再递归导入；其余走 import_file。返回 {status, message, ...}。"""
    p = p.resolve()
    name = p.name

    # 压缩包：解压到知识库 Temp 并递归导入内部文件
    if p.suffix.lower() == ".zip":
        result = extract_and_import(p, failed_dir)
        # 压缩包本体无论成功/失败都归入已处理（内部文件已逐一遍历导入）
        _move_file(p, done_dir)
        return result

    # 重复即跳过：命中知识库已有内容直接归档，不解析（2026-08-29）
    if SKIP_DUPLICATE:
        dup = _precheck_duplicate(p)
        if dup:
            logger.info(f"{name} -> duplicate(预查重跳过): 与知识库 {dup['file_name']} 同内容，直接归档")
            _move_file(p, done_dir)
            return dup

    try:
        result = import_file(p)
    except Exception as e:
        logger.error(f"导入异常 {name}: {e}")
        return {"status": "error", "message": str(e)}

    status = result.get("status") if isinstance(result, dict) else "ok"

    if status in ("success", "ok", "duplicate", "failed"):
        # 已解析成功的（含 duplicate 复用）→ 已处理；failed 也归入已处理但记录原因
        target_dir = done_dir
        note = result.get("message", "") if status in ("duplicate", "failed") else ""
        if note:
            logger.info(f"{name} -> {status}: {note}")
        _move_file(p, target_dir)
        return result

    # error / 不支持的类型 → 失败区
    msg = result.get("message", str(result)) if isinstance(result, dict) else str(result)
    logger.warning(f"{name} -> {status}: {msg}")
    _move_file(p, failed_dir)
    return result


def _fix_zip_name(info) -> str:
    """修复 zip 中文文件名乱码：未声明 UTF-8(flag 0x800) 时按 GBK 解码。

    Windows 下用第三方工具打包的中文 zip 常为 GBK 编码，zipfile 默认按 cp437
    解码导致乱码。此函数返回修正后的成员名。
    """
    name = info.filename
    if info.flag_bits & 0x800:  # UTF-8 标志已设，无需修复
        return name
    if all(ord(c) < 128 for c in name):  # 纯 ASCII 无需修复
        return name
    try:
        fixed = name.encode("cp437").decode("gbk")
        return fixed
    except Exception:
        return name


def extract_and_import(zip_path: Path, failed_dir: Path, depth: int = 0) -> dict:
    """解压 zip 到知识库 Temp/extracted/ 并递归导入内部文件。

    防重复：解压目录按 zip 内容哈希命名，已解压过则直接复用导入结果；
    且 zip 本体处理后即归档，不会重复触发。
    """
    import hashlib
    import zipfile

    if depth > 4:
        return {"status": "failed", "message": f"嵌套过深(>{depth}层)，跳过: {zip_path.name}"}

    try:
        from src.core.config import get_config

        tmp_root = get_config().temp_dir / "extracted"
        tmp_root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()[:16]
        target = tmp_root / digest

        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
            try:
                with zipfile.ZipFile(zip_path) as zf:
                    for info in zf.infolist():
                        member = info.filename
                        m = Path(member)
                        # 防路径穿越：拒绝绝对路径与 .. 段
                        if m.is_absolute() or ".." in m.parts:
                            logger.warning(f"跳过危险路径成员: {member} ({zip_path.name})")
                            continue
                        try:
                            # 中文文件名修复：zip 未声明 UTF-8 时按 GBK 重命名（Windows 常见）
                            name = _fix_zip_name(info)
                            zf.extract(info, target)
                            if name != info.filename:
                                src = target / member
                                dst = target / name
                                if src.exists() and src != dst:
                                    dst.parent.mkdir(parents=True, exist_ok=True)
                                    shutil.move(str(src), str(dst))
                        except Exception as e:
                            logger.warning(f"解压成员失败 {member}: {e}")
                logger.info(f"已解压: {zip_path.name} -> {digest}")
            except Exception as e:
                logger.error(f"解压失败: {zip_path.name} - {e}")
                return {"status": "failed", "message": f"解压失败: {e}"}
    except Exception as e:
        return {"status": "failed", "message": f"解压准备失败: {e}"}

    # 递归导入解压出的文件
    results = []
    for f in sorted(target.rglob("*")):
        if not f.is_file() or f.name.startswith("~$"):
            continue
        if f.suffix.lower() in SKIP_EXTENSIONS:
            continue
        try:
            if f.suffix.lower() == ".zip":
                r = extract_and_import(f, failed_dir, depth + 1)
            elif SKIP_DUPLICATE and _precheck_duplicate(f):
                r = {"status": "duplicate", "message": "预查重跳过"}
                logger.info(f"{f.name} -> duplicate(预查重跳过): 已存在于知识库，跳过解析")
            else:
                r = import_file(f)
            results.append(r)
        except Exception as e:
            logger.error(f"导入异常 {f.name}: {e}")
            results.append({"status": "error", "message": str(e)})

    ok = sum(1 for r in results if isinstance(r, dict) and r.get("status") in ("success", "ok", "duplicate"))
    logger.info(f"压缩包导入汇总: {zip_path.name} -> 成功 {ok}/{len(results)}")
    return {
        "status": "success" if ok or not results else "failed",
        "file_count": len(results),
        "ok": ok,
        "message": f"解压并导入 {ok}/{len(results)} 个文件",
    }


def _move_file(p: Path, target_dir: Path):
    """移入目标目录，**保留文件在入口内的相对目录结构**（避免同名冲突，便于事后核对）。"""
    try:
        rel = p.relative_to(ENTRY)
    except ValueError:
        rel = Path(p.name)
    dest = target_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest = dest.parent / f"{p.stem}_{int(time.time())}{p.suffix}"
    try:
        shutil.move(str(p), str(dest))
        try:
            shown = dest.relative_to(ENTRY)
        except ValueError:
            shown = dest
        logger.info(f"已归档: {p.name} -> {shown}")
    except Exception as e:
        logger.error(f"归档失败 {p.name}: {e}")


def rebuild_relations():
    """重建 belongs_to_subsystem 关联（幂等，与新图建立联系）。"""
    try:
        from scripts.build_file_relations import main as br_main
        import argparse
        sys.argv = ["build_file_relations", "--yes"]
        br_main()
        logger.info("belongs_to_subsystem 关联已重建")
    except Exception as e:
        logger.warning(f"关系重建失败（不影响导入）: {e}")


def scan_once() -> int:
    """扫描入口，处理所有待导入文件。返回处理数量。"""
    if not ENTRY.is_dir():
        return 0
    date_str = datetime.now().strftime("%Y%m%d")
    if RECYCLE_ORIGINAL:
        # 原件不再保留：导入后直接送入回收中转站，按 日期/结果 分目录
        base = RECYCLE_DIR / datetime.now().strftime("%Y-%m-%d")
        done_dir = base / "已导入"
        failed_dir = base / "失败"
    else:
        done_dir = ENTRY / "_已处理" / date_str
        failed_dir = ENTRY / "_失败" / date_str

    files = []
    for f in ENTRY.rglob("*"):
        if not f.is_file() or f.name.startswith("~$"):
            continue
        if f.suffix.lower() in SKIP_EXTENSIONS:
            continue
        if any(seg in SKIP_DIRS for seg in f.relative_to(ENTRY).parts[:-1]):
            continue
        files.append(f)
    files.sort(key=lambda f: (f.suffix.lower() in CAD_EXTENSIONS, str(f)))  # 文档优先，CAD 后处理

    n = 0
    for f in files:
        # 跳过正处于写入中的文件
        if not wait_stable(f):
            logger.warning(f"文件持续写入中，跳过本轮: {f.name}")
            continue
        logger.info(f"开始导入: {f.name}")
        r = process_file(f, done_dir, failed_dir)
        n += 1
        if n % 10 == 0:
            rebuild_relations()
    if n:
        rebuild_relations()
    return n


def main():
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers.polling import PollingObserver

    logger.info(f"资料库入口监听启动: {ENTRY}")
    ENTRY.mkdir(parents=True, exist_ok=True)

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event):
            # 收到事件后延迟扫描，让文件拷完；实际扫描自带稳定检测
            pass

    observer = PollingObserver(timeout=5)
    observer.schedule(Handler(), str(ENTRY), recursive=True)
    observer.start()

    try:
        scan_once()  # 启动先处理存量
        while True:
            time.sleep(15)  # ponytail: 15s 轮询足够，事件驱动需更复杂的状态机
            scan_once()
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
