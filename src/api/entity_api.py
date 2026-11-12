# -*- coding: utf-8 -*-
"""
entity_api.py — 工程实体 REST API（第四阶段，中等预留）
===========================================================
为未来 Web/App 提供工程实体（车间/设备/关联）查询与确认。
数据源：工程工作区 entity_graph.db（工程隔离）。

端点：
  GET /api/entities/workshops                车间列表
  GET /api/entities/devices?workshop=&q=     设备列表
  GET /api/entities/device/{tag}/relations   设备详情+关联
  POST /api/entities/site-links/confirm      确认/驳回 资料↔设备关联
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/entities", tags=["entities"])

PROJECT_DIR = Path(os.environ.get(
    "SITE_PROJECT_DIR", r"D:/WorkBuddy/Projects/PRJ-2026-001_Manono"))
ENTITY_DIR = PROJECT_DIR / "02_数据库" / "entity_graph"
REGISTRY = Path(r"D:/WorkBuddy/MASTER/projects.json")

sys.path.insert(0, str(ENTITY_DIR))
import entity_graph  # noqa: E402


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
    return PROJECT_DIR


def _activate(project: str = "") -> None:
    """切换活动工程实体库。"""
    entity_graph.set_project(str(_project_root(project)))


class LinkConfirmReq(BaseModel):
    sha256: str
    tag_no: str
    status: str   # confirmed / rejected


@router.get("/workshops", summary="车间列表")
def workshops(project: str = "") -> list:
    _activate(project)
    return entity_graph.list_workshops()


@router.get("/devices", summary="设备列表（可按车间/关键词过滤）")
def devices(workshop: str = "", q: str = "", project: str = "") -> list:
    _activate(project)
    return entity_graph.list_devices(workshop=workshop, q=q)


@router.get("/device/{tag}/relations", summary="设备详情 + 现场资料关联 + 设备关系")
def device_detail(tag: str, project: str = "") -> dict:
    _activate(project)
    return entity_graph.device_relations(tag)


@router.post("/site-links/confirm", summary="确认/驳回 现场资料↔设备 关联建议")
def confirm_link(req: LinkConfirmReq) -> dict:
    if req.status not in ("confirmed", "rejected"):
        return {"status": "error", "message": "status 必须为 confirmed/rejected"}
    ok = entity_graph.confirm_link(req.sha256, req.tag_no, req.status)
    return {"status": "ok" if ok else "not_found"}
