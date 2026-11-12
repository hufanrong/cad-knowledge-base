# -*- coding: utf-8 -*-
"""project_filter.py — 检索结果按项目隔离（多项目管理平台 P1）。

规则（老板拍板 2026-08-30）：
  - 平台级通用资料：files.project_id = ""（规范/标准等，所有工程可用）
  - 工程资料：files.project_id = <工程 id>（设计图纸/安装资料/现场记录/厂家资料）
  - 双层检索：请求某工程时，命中 平台级(空) + 本工程 的资料；不命中其他工程

实现：结果级过滤——按结果携带的 drawing_id / metadata.file_id
反向查 files 表 project_id，保留 空串 或 等于请求项目 的结果。
查不到归属的（如纯 CAD handle 命中）保守保留（按平台级处理，不误杀）。
"""
from __future__ import annotations

from sqlalchemy import text

from src.database.connection import get_session
from src.database.models import FileModel
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.project_filter")


def list_projects() -> list[dict]:
    """平台可用工程列表（用于界面下拉/API 枚举）。

    数据源：files.project_id 去重统计；优先带出 projects 表的工程名。
    Returns:
        [{"project_id": str, "name": str, "file_count": int}, ...] 按文件数降序。
    """
    session = get_session()
    try:
        rows = session.execute(
            text("""SELECT project_id, COUNT(*) AS cnt
                    FROM files
                    WHERE project_id IS NOT NULL AND project_id != ''
                    GROUP BY project_id
                    ORDER BY cnt DESC""")
        ).fetchall()

        # 关联 projects 表取工程名（该表可能为空或结构不一致，尽力而为）
        name_map: dict[str, str] = {}
        try:
            from src.database.models import ProjectModel

            for p in session.query(ProjectModel).all():
                if getattr(p, "project_id", None) and getattr(p, "name", None):
                    name_map[p.project_id] = p.name
        except Exception as e:
            logger.warning(f"projects 表名称读取失败（用 project_id 兜底）: {e}")

        return [
            {
                "project_id": r[0],
                "name": name_map.get(r[0], r[0]),
                "file_count": r[1],
            }
            for r in rows
        ]
    finally:
        session.close()


def _collect_ids(results: list[dict]) -> tuple[set, set]:
    """收集结果的 file_id 与 drawing_id 集合（两套都可能指向 files 表）。"""
    fids: set[str] = set()
    dwg_ids: set[str] = set()
    for r in results or []:
        did = r.get("drawing_id") or ""
        if did:
            dwg_ids.add(did)
        meta = r.get("metadata") or {}
        if isinstance(meta, dict):
            fid = meta.get("file_id") or meta.get("file") or ""
            if fid:
                fids.add(fid)
    return fids, dwg_ids


def _load_project_map(fids: set, dwg_ids: set) -> tuple[dict, dict]:
    """从 files 表加载 file_id→pid 与 drawing_id→pid 映射。"""
    fid_map: dict[str, str] = {}
    dwg_map: dict[str, str] = {}
    if not fids and not dwg_ids:
        return fid_map, dwg_map
    session = get_session()
    try:
        from sqlalchemy import or_

        conds = []
        if fids:
            conds.append(FileModel.file_id.in_(fids))
        if dwg_ids:
            conds.append(FileModel.drawing_id.in_(dwg_ids))
        rows = session.query(
            FileModel.file_id, FileModel.drawing_id, FileModel.project_id
        ).filter(or_(*conds)).all()
    except Exception as e:
        logger.warning(f"project_map 查询失败: {e}")
        return {}, {}
    finally:
        session.close()
    for fid, dwg, pid in rows:
        if fid:
            fid_map[fid] = pid or ""
        if dwg:
            dwg_map[dwg] = pid or ""
    return fid_map, dwg_map


def filter_by_project(results: list[dict], project_id: str) -> list[dict]:
    """按项目过滤检索结果（双层检索：平台级空串 + 本工程）。

    project_id 为空/None → 平台级查询，不做过滤（返回原结果）。
    """
    if not project_id:
        return results
    fids, dwg_ids = _collect_ids(results)
    fid_map, dwg_map = _load_project_map(fids, dwg_ids)

    kept: list[dict] = []
    filtered = 0
    for r in results or []:
        did = r.get("drawing_id") or ""
        meta = r.get("metadata") or {}
        fid = (meta.get("file_id") or meta.get("file") or "") if isinstance(meta, dict) else ""
        pid = fid_map.get(fid) or dwg_map.get(did) or ""
        if pid in ("", project_id):   # 平台级 或 本工程
            kept.append(r)
        else:
            filtered += 1
    if filtered:
        logger.info(f"项目过滤 {project_id}: 保留 {len(kept)}，剔除 {filtered}")
    return kept
