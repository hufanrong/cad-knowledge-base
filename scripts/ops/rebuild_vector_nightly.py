# -*- coding: utf-8 -*-
"""rebuild_vector_nightly.py — 夜间向量索引重建运行器（一次性任务用）

背景（2026-11-12）
------------------------------------------------------------------
旧 `VectorDB/` 的 HNSW 索引文件为旧格式 / 头部损坏，chromadb 1.5.9 加载时
按损坏的 header 算出天文数字的 max_elements，直接 OOM 把 API 进程 abort
（日志：`memory allocation of 33554432 bytes failed`）。
旧目录原样保留备查，配置已切到新的空库 `VectorDB_v2/`，需要重建向量。

本脚本按「停 → 建 → 起 → 验」四步跑，避免重建期间 API 进程持有同一个
Chroma 目录造成 sqlite 锁冲突：

  1. 停：结束监听 8100 的进程（夜间无人在用；随后会拉起）
  2. 建：python -m src.cli.main rebuild-index --embeddings（写 VectorDB_v2）
  3. 起：触发计划任务 WB_RestartServices（与日常重启同一通道）
  4. 验：轮询 /api/status，把 vector_backend / vector_chunks 写进日志

日志：D:/WorkBuddy/MASTER/logs/rebuild_vector.log（UTF-8，追加）

用法：
  python scripts/ops/rebuild_vector_nightly.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
PY = r"C:/Users/hufanrong/.workbuddy/binaries/python/versions/3.13.12.old.11896/python.exe"
LOG = Path(r"D:/WorkBuddy/MASTER/logs/rebuild_vector.log")
API_STATUS = "http://127.0.0.1:8100/api/status"
RESTART_TASK = "WB_RestartServices"


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _get(url: str, timeout: float = 20.0):
    """访问本机接口：显式绕过系统代理（否则 127.0.0.1 会被代理拦截）。"""
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with op.open(url, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return None, repr(e)


def stop_api() -> None:
    """结束监听 8100 的进程（找不到就跳过，不报错）。"""
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, check=False,
        ).stdout.decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        log(f"[stop] netstat 失败，跳过: {e}")
        return
    pids = set()
    for row in out.splitlines():
        parts = row.split()
        if len(parts) >= 5 and parts[1].endswith(":8100") and parts[3] == "LISTENING":
            pids.add(parts[4])
    if not pids:
        log("[stop] 未发现 8100 监听进程（可能已停）")
        return
    for pid in pids:
        subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, check=False)
        log(f"[stop] 已结束 8100 进程 PID={pid}")


def start_services() -> None:
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Start-ScheduledTask -TaskName '{RESTART_TASK}'"],
        capture_output=True, check=False,
    )
    log(f"[start] 已触发 {RESTART_TASK}")


def wait_ready(deadline_s: int = 120) -> bool:
    end = time.time() + deadline_s
    while time.time() < end:
        st, _ = _get(API_STATUS, 10)
        if st == 200:
            return True
        time.sleep(3)
    return False


def main() -> int:
    log("=" * 60)
    log("夜间向量重建开始")

    stop_api()

    log("[build] 执行 rebuild-index --embeddings（输出并入本日志）")
    t0 = time.time()
    fh = open(LOG, "a", encoding="utf-8")
    try:
        proc = subprocess.run(
            [PY, "-u", "-m", "src.cli.main", "rebuild-index", "--embeddings"],
            cwd=str(PROJECT_DIR), stdout=fh, stderr=subprocess.STDOUT, check=False,
        )
        rc = proc.returncode
    finally:
        fh.close()
    log(f"[build] 结束 returncode={rc} 耗时 {(time.time() - t0) / 60:.1f} 分钟")

    start_services()
    if not wait_ready():
        log("[verify] API 未在 120s 内就绪，请人工检查 "
            "D:/WorkBuddy/MASTER/logs/cadkb_api.log")
        return 2

    st, data = _get(API_STATUS, 60)
    if st != 200:
        log(f"[verify] /api/status 异常: {st} {data}")
        return 2
    chunks = data.get("vector_chunks")
    log(f"[verify] vector_backend={data.get('vector_backend')} "
        f"vector_chunks={chunks} texts={data.get('texts')}")
    if isinstance(chunks, int) and chunks > 0:
        log("[verify] 向量索引已恢复")
        return 0
    log("[verify] 向量仍为 0，需排查")
    return 1


if __name__ == "__main__":
    sys.exit(main())
