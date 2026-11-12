# -*- coding: utf-8 -*-
"""
site_api.py — 现场资料 REST API（第三/四阶段，中等预留）
===========================================================
为未来 Web/App 提供现场资料能力（文件上传/查询/重识别）。
工程定位：环境变量 SITE_PROJECT_DIR（默认马诺诺工程），工程隔离。

端点：
  POST /api/site/upload      文件上传 → 归档到当前工程现场资料区
  GET  /api/site/files       现场资料列表（date/status/q 过滤）
  POST /api/site/reclassify  触发重识别待确认项
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel

router = APIRouter(prefix="/api/site", tags=["site"])

# 工程定位（工程隔离：默认马诺诺，可用 SITE_PROJECT_DIR 覆盖；P1 支持 ?project= 动态切）
PROJECT_DIR = Path(os.environ.get(
    "SITE_PROJECT_DIR", r"D:/WorkBuddy/Projects/PRJ-2026-001_Manono"))
SITE_DATA_DIR = PROJECT_DIR / "05_现场资料"
UPLOAD_DIR = PROJECT_DIR / "02_数据库" / "site_data"
REGISTRY = Path(r"D:/WorkBuddy/MASTER/projects.json")

sys.path.insert(0, str(UPLOAD_DIR))
import site_core  # noqa: E402


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
    """切换活动工程现场资料区。"""
    site_core.set_project(str(_project_root(project)))


class ReclassifyResp(BaseModel):
    moved: int
    pending: int
    message: str


class ImportDocReq(BaseModel):
    project: str = ""
    sha256: str = ""


class SiteFileResp(BaseModel):
    total: int
    files: list


@router.post("/upload", summary="上传现场资料文件并归档")
async def upload_file(file: UploadFile = File(...), project: str = "") -> dict:
    """接收文件 → 存临时 → 归档到现场资料区（来源 web_upload）→ 返回登记结果。"""
    _activate(project)
    manifest = site_core.load_manifest()
    # 用原始文件名落临时文件（sanitize 防路径穿越）
    safe_name = Path(file.filename or "upload.bin").name
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / safe_name
        tmp.write_bytes(await file.read())
        result = site_core.archive_file(
            tmp, manifest, dry_run=False, extract=False, source="web_upload")
    if result["status"] == "new":
        site_core.save_manifest(manifest)
        rec = result["record"]
        return {
            "status": "ok",
            "sha256": result["sha256"],
            "文件": rec["文件"],
            "原始文件名": rec["原始文件名"],
            "状态": rec["状态"],
            "AI建议": rec["AI建议"],
        }
    return {"status": "duplicate", "sha256": result["sha256"], "原文": result.get("原文", "")}


@router.post("/import-doc", summary="已归档现场资料导入 AI 知识库")
def import_doc(req: ImportDocReq) -> dict:
    """把工程 05_现场资料 已归档文件（manifest 键=sha256）导入 CAD-KB 知识库：
    注册文件（sha256 幂等）→ 标注工程 → 正文入库（复用 _extracted 缓存）→ 向量化。
    手机上传后由 portal 异步调用，供电脑端 AI 问答检索。"""
    from src.core import site_import

    if not req.sha256:
        return {"status": "error", "message": "缺少 sha256"}
    return site_import.import_archived_site_file(req.project, req.sha256)


@router.get("/files", response_model=SiteFileResp, summary="现场资料列表/查询")
def list_files(date: str = "", status: str = "", q: str = "", project: str = "") -> SiteFileResp:
    _activate(project)
    files = site_core.query_site_files(date=date, status=status, q=q)
    return SiteFileResp(total=len(files), files=files)


@router.post("/reclassify", response_model=ReclassifyResp, summary="重识别待确认项")
def reclassify(project: str = "") -> ReclassifyResp:
    _activate(project)
    manifest = site_core.load_manifest()
    before = sum(1 for r in manifest["记录"].values() if r["状态"] == "待确认")
    site_core.reclassify()
    manifest = site_core.load_manifest()
    after = sum(1 for r in manifest["记录"].values() if r["状态"] == "待确认")
    return ReclassifyResp(moved=before - after, pending=after,
                          message="重识别完成")
