# -*- coding: utf-8 -*-
"""restart_cadkb_api.py — 重启 CAD-KB REST API（默认 8100）
用途：.env 配置变更（如 LLM API Key）后热生效；服务异常时恢复。
仅动 API 端口，不影响 portal 8000 / 外网隧道。
用法：python scripts/ops/restart_cadkb_api.py [port]

注意：本脚本位于 scripts/ops/，项目根按 parents[2] 推导；若再移动目录需同步修改。
"""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8100
PYTHON = sys.executable
LOG_DIR = PROJECT_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def kill_port(port: int) -> None:
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, check=False
        ).stdout.decode("utf-8", errors="replace")
        for line in out.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                pid = line.split()[-1]
                if pid.isdigit():
                    subprocess.run(["taskkill", "/PID", pid, "/F"],
                                   capture_output=True, check=False)
                    print(f"已终止占用 {port} 的进程 PID={pid}")
    except Exception as e:
        print(f"释放端口失败: {e}")


def is_up(port: int) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/health", timeout=3
        ) as r:
            return r.status == 200
    except Exception:
        return False


def main() -> int:
    kill_port(PORT)
    time.sleep(1)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_DIR)
    env["CADKB_LOG_FILE"] = "api.log"
    log_file = LOG_DIR / "api.log"
    flags = 0
    if hasattr(subprocess, "CREATE_NEW_CONSOLE"):
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE")
    proc = subprocess.Popen(
        [str(PYTHON), "-m", "src.cli.main", "serve", "--port", str(PORT)],
        cwd=PROJECT_DIR,
        env=env,
        stdout=open(log_file, "w", encoding="utf-8", errors="replace"),
        stderr=subprocess.STDOUT,
        creationflags=flags,
    )
    print(f"API 进程已启动 PID={proc.pid}，等待就绪 ...")
    for _ in range(120):
        if is_up(PORT):
            print(f"API 就绪: http://127.0.0.1:{PORT}/api/health")
            return 0
        time.sleep(1)
    print("等待超时，请查看日志:", log_file)
    return 1


if __name__ == "__main__":
    sys.exit(main())
