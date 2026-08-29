"""阶段6验收脚本。"""
from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from src.core.export_service import export_device_profiles


def check_api_manual():
    p = Path("D:/WorkBuddy/outputs/projects/2026-08-17-14-05-54/CAD-Knowledge-Base/docs/API_MANUAL.md")
    assert p.exists(), f"API 手册不存在: {p}"
    text = p.read_text(encoding="utf-8")
    assert "GET /api/devices" in text
    assert "GET /api/search-all" in text
    print("[OK] API 手册已生成")


def check_export():
    out = Path("D:/WorkBuddy/work/data/knowledge_base/Temp/exports/stage6_verify.xlsx")
    path = export_device_profiles(out, subsystem_no="0203")
    assert path.exists()
    wb = load_workbook(path)
    ws = wb.active
    assert ws.max_row > 1
    headers = [cell.value for cell in ws[1]]
    assert "位号" in headers
    print(f"[OK] Excel 导出: {ws.max_row - 1} 条设备")


def check_backup():
    files = sorted(Path("D:/WorkBuddy/work/data/knowledge_base/Temp").glob("cadkb_backup_*_pre_stage6.db"))
    assert files, "阶段6备份不存在"
    import sqlite3
    conn = sqlite3.connect(str(files[-1]))
    n = conn.execute("SELECT COUNT(*) FROM drawings").fetchone()[0]
    conn.close()
    assert n == 515, f"备份图纸数异常: {n}"
    print(f"[OK] 数据库备份: {files[-1].name} | drawings={n}")


def main():
    check_backup()
    check_api_manual()
    check_export()
    print("\n阶段6验收通过")


if __name__ == "__main__":
    main()
