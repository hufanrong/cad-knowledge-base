# -*- coding: utf-8 -*-
"""
report_api.py — 常规任务：日报/周报自动生成（多项目管理平台 P2）
================================================================
数据源（按项目组装）：
  - 现场记录：工程 06_现场记录（records_sync，即时扫描）
  - 现场资料：工程 05_现场资料 manifest（site_core）
  - 实体统计：工程 entity_graph（车间/设备）

生成：
  - 有 LLM（DeepSeek）→ AI 生成 Markdown 报告 + 来源可追溯
  - 无 LLM → 证据模式：结构化数据摘要（不编造）

端点：POST /api/report
  body: {project: "manono", doc_type: "daily"|"weekly", period: "2026-08-30"
         | "2026-08-24~2026-08-30", workshop: ""}
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.llm import get_llm_client
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.report")

router = APIRouter(prefix="/api/report", tags=["report"])

REGISTRY = Path(r"D:/WorkBuddy/MASTER/projects.json")
DEFAULT_ROOT = Path(r"D:/WorkBuddy/Projects/PRJ-2026-001_Manono")


def _project_root(project: str = "") -> Path:
    """按项目 id 解析工程根目录（注册表）；未命中回退默认 manono。"""
    if project:
        try:
            data = json.loads(REGISTRY.read_text(encoding="utf-8"))
            for p in data.get("projects", []):
                if p.get("id") == project:
                    return Path(p["root"])
        except Exception:
            pass
    return DEFAULT_ROOT


def _load_engine(root: Path):
    """注入工程 site_data/site_record/entity_graph 模块并切换活动工程。"""
    site_data = root / "02_数据库" / "site_data"
    site_record = site_data / "site_record"      # records_sync.py 所在
    entity_dir = root / "02_数据库" / "entity_graph"
    for p in (site_data, site_record, entity_dir):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import site_core
    import records_sync
    import entity_graph
    site_core.set_project(str(root))
    entity_graph.set_project(str(root))
    return site_core, records_sync, entity_graph


def _parse_period(doc_type: str, period: str) -> list[str]:
    """返回日期列表。daily: 单日；weekly: ~ 分隔区间（含首尾）。"""
    if not period:
        today = datetime.now().strftime("%Y-%m-%d")
        if doc_type == "weekly":
            start = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
            return [start, today]
        return [today]
    if "~" in period:
        a, b = period.split("~", 1)
        start = datetime.strptime(a.strip(), "%Y-%m-%d")
        end = datetime.strptime(b.strip(), "%Y-%m-%d")
        return [(start + timedelta(days=i)).strftime("%Y-%m-%d")
                for i in range((end - start).days + 1)]
    return [period.strip()]


class ReportReq(BaseModel):
    project: str = Field("manono", description="工程 id")
    doc_type: str = Field("daily", description="daily 日报 | weekly 周报")
    period: str = Field("", description="日期 YYYY-MM-DD 或 区间 A~B；空=今天/近7天")
    workshop: str = Field("", description="限定车间（可选）")


class ReportResp(BaseModel):
    content: str = ""
    mode: str = "evidence"
    llm_model: str = ""
    traceable: int = 0
    sources: list = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)


@router.post("", response_model=ReportResp, summary="生成日报/周报（按项目）")
def generate_report(req: ReportReq):
    root = _project_root(req.project)
    try:
        site_core, records_sync, entity_graph = _load_engine(root)
    except Exception as e:
        logger.warning(f"工程模块加载失败: {e}")
        return ReportResp(content=f"❌ 无法加载工程 {req.project} 数据模块：{e}")

    dates = _parse_period(req.doc_type, req.period)
    proj_root = root

    # 1) 现场记录
    records = records_sync.list_records(project_root=proj_root)
    recs = [r for r in records if r["日期"] in dates]
    if req.workshop:
        recs = [r for r in recs if req.workshop in r["车间"]]

    # 2) 现场资料（当天新增/待确认）
    files = site_core.query_site_files()
    files_in = [f for f in files
                if (f.get("接收时间") or "").startswith(tuple(dates)) or
                (f.get("文件") or "").startswith(tuple(dates))]

    # 3) 实体统计
    try:
        ws = entity_graph.list_workshops()
        dev_count = len(entity_graph.list_devices())
    except Exception:
        ws, dev_count = [], 0

    stats = {
        "工程": req.project,
        "周期": " ~ ".join(dates) if len(dates) > 1 else dates[0],
        "记录数": len(recs),
        "车间数": len(ws),
        "设备数(上限500)": dev_count,
        "现场资料": len(files_in),
        "待确认": sum(1 for f in files_in if f.get("状态") == "待确认"),
    }

    # 4) 组装数据文本（供 LLM 生成或证据模式直出）
    lines = [f"# {req.project} 工程{'周' if req.doc_type=='weekly' else '日'}报（{' ~ '.join(dates)}）"]
    lines.append("")
    lines.append("## 一、现场记录")
    if recs:
        by_ws: dict[str, int] = {}
        for r in recs:
            by_ws[r["车间"]] = by_ws.get(r["车间"], 0) + 1
        lines.append("车间分布：" + "；".join(f"{k} {n}条" for k, n in sorted(by_ws.items())))
        lines.append("")
        for r in recs:
            lines.append(f"- [{r['日期']}] **{r['车间']}**：{(r['内容'] or '(无文字)')[:120]}")
            if r.get("照片数"):
                lines.append(f"  （照片 {r['照片数']} 张）")
    else:
        lines.append("（本期无现场记录）")
    lines.append("")
    lines.append("## 二、现场资料")
    lines.append(f"本期涉及 {len(files_in)} 份（待确认 {stats['待确认']}）")
    for f in files_in[:10]:
        lines.append(f"- {f.get('原始文件名', f.get('文件', ''))[:70]} [{f.get('状态','')}]")
    if len(files_in) > 10:
        lines.append(f"- …（共 {len(files_in)} 份）")
    lines.append("")
    lines.append("## 三、实体概况")
    lines.append(f"- 车间 {len(ws)} 个；设备（实体库）{dev_count} 台")
    data_text = "\n".join(lines)

    sources = [{"file": r.get("内容", "")[:40], "日期": r["日期"]} for r in recs[:10]]

    # 5) LLM 生成（有 key 才调用；失败自动降级证据模式）
    llm = get_llm_client()
    if llm.available:
        try:
            sys_prompt = (
                "你是工程施工管理报告助手。根据提供的结构化数据，"
                "生成简洁的中文工程日报/周报 Markdown，突出：关键进展、待办问题、"
                "数据要点。只基于给定数据，不编造。"
            )
            answer = llm.chat([
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": f"请生成报告：\n\n{data_text}"},
            ], max_tokens=1200)
            return ReportResp(content=answer, mode="llm", llm_model=llm.model,
                              traceable=len(recs), sources=sources, stats=stats)
        except Exception as e:
            logger.warning(f"LLM 报告生成失败，降级证据模式: {e}")

    return ReportResp(content=data_text, mode="evidence",
                      traceable=len(recs), sources=sources, stats=stats)
