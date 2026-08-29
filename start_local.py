"""启动 CAD 知识库本地服务（GUI + API）。

双击 start_local.bat 或直接运行本脚本：
    python start_local.py

数据仅保存在本机，不上传任何云端。
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
PYTHON = Path(r"C:\Users\hufanrong\.workbuddy\binaries\python\versions\3.13.12\python.exe")
LOG_DIR = PROJECT_DIR / "logs"
API_PORT = 8000
GUI_PORT = 8501
API_URL = f"http://127.0.0.1:{API_PORT}/api/health"
GUI_URL = f"http://localhost:{GUI_PORT}/_stcore/health"

procs: list[subprocess.Popen] = []


def _log(msg: str) -> None:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


def _kill_port(port: int) -> None:
    """Kill processes occupying a given port (Windows netstat + taskkill)."""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            check=False,
        )
        # netstat output may use system default encoding (often GBK on Chinese Windows)
        stdout = result.stdout.decode("utf-8", errors="replace")
        if not stdout:
            stdout = result.stdout.decode("gbk", errors="replace")
        for line in stdout.splitlines():
            if f":{port}" in line and ("LISTENING" in line or "ESTABLISHED" in line):
                parts = line.split()
                if parts:
                    pid = parts[-1]
                    if pid.isdigit():
                        _log(f"关闭端口 {port} 占用进程 PID={pid}")
                        subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, check=False)
    except Exception as e:
        _log(f"释放端口 {port} 时出错: {e}")


def _start_api() -> subprocess.Popen:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_DIR)
    env["CADKB_LOG_FILE"] = "api.log"
    log_file = LOG_DIR / "api.log"
    _log(f"启动 REST API: http://127.0.0.1:{API_PORT}")
    return subprocess.Popen(
        [
            str(PYTHON),
            "-m",
            "src.cli.main",
            "serve",
            "--port",
            str(API_PORT),
        ],
        cwd=PROJECT_DIR,
        env=env,
        stdout=open(log_file, "w", encoding="utf-8", errors="replace"),
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )


def _start_gui() -> subprocess.Popen:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_DIR)
    env["CADKB_LOG_FILE"] = "gui.log"
    log_file = LOG_DIR / "gui.log"
    _log(f"启动 Streamlit GUI: http://localhost:{GUI_PORT}")
    return subprocess.Popen(
        [
            str(PYTHON),
            "-m",
            "streamlit",
            "run",
            "src/gui/app.py",
            "--server.port",
            str(GUI_PORT),
            "--server.headless",
            "true",
        ],
        cwd=PROJECT_DIR,
        env=env,
        stdout=open(log_file, "w", encoding="utf-8", errors="replace"),
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )


def _is_up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            return resp.status in (200, 307)
    except Exception:
        return False


def _wait_for(label: str, url: str, timeout: int = 120) -> bool:
    _log(f"等待 {label} 就绪 ...")
    start = time.time()
    while time.time() - start < timeout:
        if _is_up(url):
            _log(f"{label} 已就绪")
            return True
        time.sleep(1)
    _log(f"{label} 在 {timeout} 秒内未就绪")
    return False


def _open_browser() -> None:
    url = f"http://localhost:{GUI_PORT}"
    _log(f"正在打开浏览器: {url}")
    try:
        webbrowser.open(url, new=2)
    except Exception as e:
        _log(f"自动打开浏览器失败，请手动访问 {url}: {e}")


def _cleanup(signum=None, frame=None) -> None:
    _log("正在关闭服务 ...")
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    for p in procs:
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()
    _log("服务已关闭")
    sys.exit(0)


def main() -> int:
    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    _log("==========================================")
    _log("  CAD 知识库 - 本地启动")
    _log("  数据仅保存在本机，不上传任何云端")
    _log("==========================================")

    _kill_port(GUI_PORT)
    _kill_port(API_PORT)

    global procs
    procs.append(_start_api())
    time.sleep(2)
    procs.append(_start_gui())

    api_ok = _wait_for("API", API_URL, timeout=120)
    gui_ok = _wait_for("GUI", GUI_URL, timeout=120)

    if not (api_ok and gui_ok):
        _log("服务未在预期时间内就绪，请查看日志:")
        _log(f"  {LOG_DIR / 'api.log'}")
        _log(f"  {LOG_DIR / 'gui.log'}")
        _cleanup()
        return 1

    _open_browser()

    _log("==========================================")
    _log("  启动完成")
    _log(f"  GUI:  http://localhost:{GUI_PORT}")
    _log(f"  API:  http://127.0.0.1:{API_PORT}")
    _log(f"  文档: http://127.0.0.1:{API_PORT}/docs")
    _log(f"  日志: {LOG_DIR}")
    _log("  按 Ctrl+C 关闭服务")
    _log("==========================================")

    try:
        while True:
            for p in procs:
                if p.poll() is not None:
                    _log("某个服务已退出，正在清理 ...")
                    _cleanup()
                    return 1
            time.sleep(2)
    except KeyboardInterrupt:
        _cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
