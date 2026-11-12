# -*- coding: utf-8 -*-
"""
site_import.py — 现场资料 → AI 知识库导入（多项目平台二期）
================================================================
把工程 05_现场资料 已归档（manifest）的文件导入 CAD-KB 知识库：
  1. register_file（sha256 幂等，重复自动跳过）
  2. assign_project（**直接传字符串工程 id，不走 get_or_create_project**——
     本库 files.project_id 存的是 'manono' 这种字符串而非 UUID）
  3. 内容入库：优先复用 site_core._extracted/<sha256>.txt 正文缓存（免二次解析），
     写 document_contents + documents_fts
  4. 重置 VectorIndex._proj_map（进程级缓存，不重置则新向量不带工程标签，
     AI 问答按 project_id 过滤检索不到）
  5. index_document_content 向量化

入口：site_api.py `POST /api/site/import-doc {project, sha256}`
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(r"D:/WorkBuddy/Projects/PRJ-2026-001_Manono")
REGISTRY = Path(r"D:/WorkBuddy/MASTER/projects.json")
CADKB = Path(r"D:/WorkBuddy/outputs/projects/2026-08-17-14-05-54/CAD-Knowledge-Base")

sys.path.insert(0, str(PROJECT_DIR / "02_数据库" / "site_data"))
sys.path.insert(0, str(CADKB))

import site_core  # noqa: E402
import src.index.vector_index as vector_index_mod  # noqa: E402
from sqlalchemy import text  # noqa: E402

from src.database.connection import get_session  # noqa: E402
from src.database.models import DocumentContentModel  # noqa: E402
from src.core.document_rag import index_document_content  # noqa: E402
from src.core.file_registry import FileRegistry  # noqa: E402

# 可导入 AI 知识库的扩展名（dwg/zip/视频等只归档不向量化）
DOC_EXTS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".xlt",
    ".ppt", ".pptx", ".txt", ".csv", ".md",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
}


def _project_root(project: str) -> Path:
    """按工程 id 解析根目录（注册表）；未命中回退 manono。"""
    if project:
        try:
            data = json.loads(REGISTRY.read_text(encoding="utf-8"))
            for p in data.get("projects", []):
                if p.get("id") == project:
                    return Path(p["root"])
        except Exception:
            pass
    return PROJECT_DIR


def import_archived_site_file(project: str, sha256: str) -> dict:
    """把工程 05_现场资料 已归档文件导入知识库。返回状态字典。"""
    root = _project_root(project)
    site_dir = root / "05_现场资料"
    site_core.set_project(str(root))
    manifest = site_core.load_manifest()
    rec = manifest["记录"].get(sha256)
    if not rec:
        return {"status": "missing", "sha256": sha256, "message": "manifest 无此记录"}

    rel = (rec.get("文件") or "").replace("\\", "/")
    src_path = site_dir / rel if rel else Path()
    if not src_path.exists():
        return {"status": "missing", "sha256": sha256, "message": f"文件不存在: {rel}"}

    ext = src_path.suffix.lower()
    if ext not in DOC_EXTS:
        return {"status": "skipped", "sha256": sha256, "message": f"非文档类({ext or '无扩展名'})，只归档不入知识库"}

    # 1. 注册（sha256 幂等）
    reg = FileRegistry()
    try:
        r = reg.register_file(str(src_path))
    finally:
        reg.close()
    file_id = r.get("file_id", "")
    if not file_id:
        return {"status": "error", "sha256": sha256, "message": r.get("message", "注册失败")}

    # 2. 标注工程（字符串 id）
    reg2 = FileRegistry()
    try:
        reg2.assign_project(file_id, project)
    finally:
        reg2.close()

    # 3. 内容入库（优先复用正文缓存）
    content_text = ""
    cache = site_dir / "_extracted" / f"{sha256}.txt"
    if cache.exists():
        content_text = cache.read_text(encoding="utf-8", errors="replace")
    if not content_text:
        content_text = site_core.extract_text(src_path)
    if not content_text and ext in (".txt", ".csv", ".md"):
        # site_core.extract_text 不覆盖纯文本类，直接读
        try:
            content_text = src_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if not content_text:
        return {"status": "no_content", "file_id": file_id, "sha256": sha256,
                "message": "未能提取正文（可能是扫描件/无文字内容）"}

    session = get_session()
    try:
        row = (
            session.query(DocumentContentModel)
            .filter(DocumentContentModel.file_id == file_id)
            .first()
        )
        if row is None:
            row = DocumentContentModel(file_id=file_id)
            session.add(row)
        row.source_type = (rec.get("文件类型") or rec.get("类别") or "document")[:50]
        row.title = rec.get("原始文件名", "")
        row.content = content_text
        row.markdown = content_text
        row.source = "site_upload"
        row.updated_at = datetime.now()
        session.commit()
        # FTS 重建（documents_fts 独立表，手动同步）
        session.execute(
            text("DELETE FROM documents_fts WHERE file_id = :fid"),
            {"fid": file_id},
        )
        session.execute(
            text(
                "INSERT INTO documents_fts (title, content, file_id, source_type) "
                "VALUES (:t, :c, :fid, :st)"
            ),
            {"t": row.title, "c": content_text, "fid": file_id, "st": row.source_type},
        )
        session.commit()
    finally:
        session.close()

    # 4. 重置工程映射缓存（关键：不重置则新向量不带 project_id）
    vector_index_mod._proj_map = None

    # 5. 向量化
    chunks = 0
    try:
        chunks = index_document_content(file_id)
    except Exception as e:  # noqa: BLE001
        return {"status": "index_failed", "file_id": file_id, "sha256": sha256,
                "message": f"向量化失败: {e}"}

    return {"status": "imported", "file_id": file_id, "sha256": sha256, "chunks": chunks}
