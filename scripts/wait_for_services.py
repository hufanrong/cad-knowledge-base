"""Wait for CAD-KB API and GUI to become healthy, then optionally open browser."""
import os
import sys
import time
import urllib.request

API_URL = os.environ.get("CADKB_API_URL", "http://127.0.0.1:8000/api/health")
GUI_URL = os.environ.get("CADKB_GUI_URL", "http://localhost:8501/_stcore/health")
TIMEOUT = int(os.environ.get("CADKB_WAIT_TIMEOUT", "120"))


def _is_up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            return resp.status in (200, 307)
    except Exception:
        return False


def wait(label: str, url: str) -> bool:
    print(f"等待 {label} ({url}) ...")
    start = time.time()
    while time.time() - start < TIMEOUT:
        if _is_up(url):
            print(f"  {label} 已就绪")
            return True
        time.sleep(1)
    print(f"  {label} 在 {TIMEOUT} 秒内未就绪")
    return False


def main() -> int:
    api_ok = wait("API", API_URL)
    gui_ok = wait("GUI", GUI_URL)
    if api_ok and gui_ok:
        print("服务全部就绪")
        if len(sys.argv) > 1 and sys.argv[1] == "--open":
            try:
                os.startfile("http://localhost:8501")
            except Exception as e:
                print(f"浏览器自动打开失败（可手动访问 http://localhost:8501）: {e}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
