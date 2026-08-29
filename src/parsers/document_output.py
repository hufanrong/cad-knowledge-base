"""Parsed document output writer — 解析产物落盘 (Phase 3).

Writes ParsedDocument into ParsedData/<SourceType>/<file_id>.{json,md,txt}.
The markdown/txt versions are LLM-friendly; JSON keeps full structure.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.core.config import get_config
from src.normalizer.schema import ParsedDocument
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.parsers.output")


def write_parsed_output(doc: ParsedDocument, file_id: str) -> dict:
    """Write parsed document to ParsedData/ and return paths."""
    config = get_config()
    out_dir = config.parsed_dir / doc.source_type
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"{file_id}.json"
    md_path = out_dir / f"{file_id}.md"
    txt_path = out_dir / f"{file_id}.txt"

    try:
        json_path.write_text(
            json.dumps(doc.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        md_path.write_text(doc.markdown or "", encoding="utf-8")
        txt_path.write_text(doc.content or "", encoding="utf-8")

        doc.json_path = str(json_path)
        doc.md_path = str(md_path)
        doc.txt_path = str(txt_path)
        logger.info(
            f"解析产物已写入: {json_path.name} "
            f"(md={len(doc.markdown)}B, txt={len(doc.content)}B)")
        return {
            "json_path": str(json_path),
            "md_path": str(md_path),
            "txt_path": str(txt_path),
        }
    except Exception as e:
        logger.error(f"解析产物写入失败: {e}")
        return {"error": str(e)}
