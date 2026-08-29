"""解析质量统计（阶段1）— 导入/解析健康度报告。

统计内容：
- 文件总数 / 按类型 / 按解析状态（success/partial/failed/pending）
- 各来源类型的解析成功率、平均内容长度
- 解析失败文件清单与原因
- 重复文件 / 多来源
- 版本情况（version_no>1 的文件）
- 无法识别/暂不可解析的文件
"""

from __future__ import annotations

import json

from sqlalchemy import func

from src.database.connection import get_session, init_database
from src.database.models import (
    DocumentContentModel,
    FileModel,
    FileSourceModel,
)
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.quality")


def quality_report() -> dict:
    """生成解析质量统计报告。"""
    init_database()
    session = get_session()
    try:
        total = session.query(func.count(FileModel.file_id)).scalar() or 0

        # 按解析状态
        status_dist = dict(
            session.query(FileModel.parse_status,
                          func.count(FileModel.file_id))
            .group_by(FileModel.parse_status).all()
        )
        # 按来源类型
        type_dist = dict(
            session.query(FileModel.source_type,
                          func.count(FileModel.file_id))
            .group_by(FileModel.source_type).all()
        )

        # 各来源类型 × 解析状态
        type_status = {}
        rows = (
            session.query(FileModel.source_type, FileModel.parse_status,
                          func.count(FileModel.file_id))
            .group_by(FileModel.source_type, FileModel.parse_status)
            .all()
        )
        for stype, status, n in rows:
            type_status.setdefault(stype, {})[status] = n

        # 失败文件（failed + pending 中不可解析的）
        failed = (
            session.query(FileModel)
            .filter(FileModel.parse_status.in_(["failed", "pending"]))
            .order_by(FileModel.original_name)
            .all()
        )
        failed_list = [
            {
                "file_name": f.original_name,
                "source_type": f.source_type,
                "status": f.parse_status,
                "file_id": f.file_id,
                "error": _file_error(f),
            }
            for f in failed
        ]

        # 文档内容长度（解析覆盖）
        doc_stats = {}
        drow = (
            session.query(DocumentContentModel.source_type,
                          func.count(DocumentContentModel.file_id),
                          func.avg(func.length(DocumentContentModel.content)))
            .group_by(DocumentContentModel.source_type)
            .all()
        )
        for stype, cnt, avg_len in drow:
            doc_stats[stype] = {
                "count": cnt,
                "avg_content_len": round(float(avg_len or 0), 1),
            }

        # 重复/多来源：有 >1 条 source 的文件
        multi_src = (
            session.query(FileSourceModel.file_id,
                          func.count(FileSourceModel.source_id))
            .group_by(FileSourceModel.file_id)
            .having(func.count(FileSourceModel.source_id) > 1)
            .count()
        )

        # 版本：version_no > 1 的文件
        ver_rows = (
            session.query(FileModel.extra)
            .filter(FileModel.extra.isnot(None))
            .all()
        )
        versioned = 0
        for (extra,) in ver_rows:
            try:
                m = json.loads(extra)
            except Exception:
                continue
            if m.get("version_no", 1) > 1:
                versioned += 1

        report = {
            "total_files": total,
            "by_status": status_dist,
            "by_type": type_dist,
            "type_x_status": type_status,
            "failed_files": failed_list,
            "failed_count": len(failed_list),
            "document_content": doc_stats,
            "multi_source_files": multi_src,
            "versioned_files": versioned,
        }
        logger.info(f"质量统计: 总 {total}, 失败 {len(failed_list)}, "
                    f"多来源 {multi_src}, 多版本 {versioned}")
        return report
    finally:
        session.close()


def _file_error(f: FileModel) -> str:
    """从 extra / 状态推导失败原因（尽力而为，不伪造）。"""
    if f.extra:
        try:
            m = json.loads(f.extra)
            if m.get("parse_error"):
                return str(m["parse_error"])
        except Exception:
            pass
    if f.parse_status == "pending":
        return "暂不可解析（未配置解析器或组件缺失）"
    return "解析失败"
