# -*- coding: utf-8 -*-
"""
migrate_project_tags.py — 回填 files.project_id（多项目管理平台 P1）
====================================================================
目标：检索按项目隔离的数据基础。
规则（老板拍板 2026-08-30）：
  - 规范/标准类（GB/行标/规范/标准/规程/导则）→ project_id=""（平台级通用）
  - 工程资料（路径/文件名含 Manono/马诺诺/冶炼厂/选矿等工程专属词）→ 注册表工程 id
  - 厂家资料（厂家/样本/manufacturer 等）→ project_id=""（平台级，两边库：平台存+工程 manifest 关联）
  - 无法判断 → 保持 None（平台级语义，不猜测）
同时清理 projects 表 862 条文件名推断噪声，按注册表重建。

用法：
  python scripts/migrate_project_tags.py            # dry-run 统计
  python scripts/migrate_project_tags.py --apply     # 写库
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CADKB = Path(r"D:/WorkBuddy/outputs/projects/2026-08-17-14-05-54/CAD-Knowledge-Base")
KB_DB = Path(r"D:/WorkBuddy/work/data/knowledge_base/database/cadkb.db")
REGISTRY = Path(r"D:/WorkBuddy/MASTER/projects.json")

sys.path.insert(0, str(CADKB))
from src.database.connection import get_session          # noqa: E402
from src.database.models import FileModel, ProjectModel  # noqa: E402

# 规范/标准类（平台级）
STANDARD_KWS = [
    "GB/T", "GB ", "GB-", "GBJ", "JGJ", "JG/T", "DL/T", "HG/T", "JB/T",
    "规范", "标准", "通则", "规程", "导则", "图集", "国标", "行标",
]
# 厂家资料类（平台级，两边库）
MANUFACTURER_KWS = ["厂家", "样本", "manufacturer", "sample", "订货资料", "说明书", "参数表"]
# 工程资料类（归属注册表工程）
PROJECT_KWS = {
    "manono": ["Manono", "MANONO", "manono", "马诺诺", "马诺", "冶炼厂", "选矿厂",
               "选厂", "锂辉石", "锂盐", "焙烧", "回转窑", "浸出", "蒸发车间",
               "硫磺制酸", "磨浮", "尾矿", "精矿", "刚果", "紫金"],
}


def load_registry_projects() -> dict:
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
        return {p["id"]: p for p in data.get("projects", [])}
    except Exception:
        return {}


def classify(original_path: str, original_name: str) -> str:
    """返回 project_id（""=平台级 / 工程 id / None=无法判断）。"""
    text = f"{original_path or ''} {original_name or ''}"
    # 1) 规范/标准（优先：通用资料只进平台级）
    if any(k in text for k in STANDARD_KWS):
        return ""
    # 2) 厂家资料（平台级，两边库）
    if any(k in text for k in MANUFACTURER_KWS):
        return ""
    # 3) 工程专属词 → 注册表工程
    for pid, kws in PROJECT_KWS.items():
        if any(k in text for k in kws):
            return pid
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="回填 files.project_id")
    ap.add_argument("--apply", action="store_true", help="写库（默认 dry-run）")
    args = ap.parse_args()

    reg = load_registry_projects()
    print(f"注册表项目: {list(reg.keys())}")

    session = get_session()
    try:
        # 1) projects 表：清噪声，按注册表重建
        old_proj = session.query(ProjectModel).count()
        session.query(ProjectModel).delete()
        for pid, p in reg.items():
            session.add(ProjectModel(
                project_id=pid, name=p.get("name", pid),
                confidence=1.0, source="registry"))
        # 2) files 回填
        files = session.query(FileModel).all()
        stat: dict[str, int] = {}
        updated = 0
        for f in files:
            pid = classify(f.original_path, f.original_name)
            if f.project_id != pid:      # 含 pid=None：清除残留 UUID（平台级语义）
                f.project_id = pid
                updated += 1
            key = "平台级" if pid == "" else (pid or "平台级(None)")
            stat[key] = stat.get(key, 0) + 1
        if args.apply:
            session.commit()
            print(f"已写库：projects 清 {old_proj} 条 → {len(reg)} 条；files 更新 {updated} 条")
        else:
            session.rollback()
            print(f"DRY-RUN：projects 将清 {old_proj} 条 → {len(reg)} 条；files 将更新 {updated} 条")
        print("files.project_id 归类统计：")
        for k, v in sorted(stat.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
