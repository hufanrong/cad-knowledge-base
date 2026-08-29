"""File import orchestrator — ties together file management, parsing, and storage."""

from datetime import datetime
from pathlib import Path

from src.database.connection import get_session, init_database
from src.database.repositories import DrawingRepository
from src.file_manager.hasher import compute_sha256
from src.file_manager.version_detector import detect_file_type, get_file_info
from src.normalizer.schema import FileType, ParseStatus
from src.parsers.dwg_parser import DWGParser
from src.parsers.dxf_parser import DXFParser
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.importer")

# 文档类扩展名（Phase 3/4: 多格式）
DOC_EXTENSIONS = {
    ".docx", ".doc", ".xlsx", ".xls", ".xlsm", ".csv",
    ".pdf", ".pptx", ".ppt", ".mpp",
    ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".gif", ".webp",
    ".rtf", ".txt", ".xml", ".json", ".html",
}

# 解析器路由（按扩展名 -> parser 名）
DOC_PARSERS = {
    ".docx": "word", ".doc": "word",
    ".xlsx": "excel", ".xls": "excel", ".xlsm": "excel", ".csv": "excel",
    ".pdf": "pdf",
    ".mpp": "project",
    ".pptx": "pptx",
    ".jpg": "image", ".jpeg": "image", ".png": "image",
    ".bmp": "image", ".tif": "image", ".tiff": "image",
    ".gif": "image", ".webp": "image",
}


def import_file(
    file_path: str | Path,
    force: bool = False,
) -> dict:
    """Import a single file into the knowledge base.

    CAD files (DWG/DXF) go through the CAD pipeline; document files
    (Word/Excel/PDF/CSV...) go through the document pipeline (Phase 3).

    Args:
        file_path: Path to the file.
        force: If True, re-parse even if file hash already exists.

    Returns:
        Dict with import result.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        return {
            "status": "error",
            "message": f"文件不存在: {path}",
        }

    # Route document formats to the document pipeline
    if path.suffix.lower() in DOC_EXTENSIONS:
        return import_document(path, force=force)

    logger.info(f"导入文件: {path.name}")

    # 1. Compute file hash
    try:
        file_hash = compute_sha256(path)
    except Exception as e:
        return {
            "status": "error",
            "message": f"文件哈希计算失败: {e}",
        }

    # 2. Get file info
    info = get_file_info(path)
    if "error" in info:
        return {"status": "error", "message": info["error"]}

    file_type = info["file_type"]

    # 3. Check for duplicates
    init_database()
    session = get_session()
    repo = DrawingRepository(session)

    if not force:
        existing = repo.find_by_hash(file_hash)
        if existing:
            logger.info(f"文件已存在(重复): {path.name}")
            return {
                "status": "duplicate",
                "drawing_id": existing.drawing_id,
                "file_name": existing.file_name,
                "message": f"文件已存在于知识库 (hash={file_hash[:16]}...)",
            }
    else:
        # Force re-import: drop old vector index entries for this hash
        existing = repo.find_by_hash(file_hash)
        if existing:
            try:
                from src.index.vector_index import VectorIndex

                VectorIndex().delete_drawing(existing.drawing_id)
            except Exception as e:
                logger.warning(f"旧向量索引清理失败: {e}")

    # 4. Select parser based on file type
    parser = _select_parser(file_type, path)
    if parser is None:
        return {
            "status": "error",
            "file_name": path.name,
            "message": _unsupported_file_message(file_type),
        }

    # 5. Parse
    try:
        result = parser.parse(path)
    except Exception as e:
        logger.error(f"解析失败: {path.name} - {e}")
        return {
            "status": "error",
            "file_name": path.name,
            "message": f"解析异常: {e}",
        }

    if result.drawing.parse_status == ParseStatus.FAILED:
        errors = "; ".join(e.get("error", str(e)) for e in result.errors)
        return {
            "status": "failed",
            "file_name": path.name,
            "message": f"解析失败: {errors}",
            "errors": result.errors,
        }

    # 5.1 Semantic analysis (Phase 3) — frame/title block/equipment/pipes
    try:
        from src.semantic import analyze as analyze_semantic

        analyze_semantic(result)
    except Exception as e:
        logger.warning(f"语义分析失败（不影响解析结果）: {path.name} - {e}")

    # 5.2 Spatial analysis (Phase 4) — proximity/contains/annotates
    try:
        from src.spatial import analyze as analyze_spatial

        analyze_spatial(result)
    except Exception as e:
        logger.warning(f"空间分析失败（不影响解析结果）: {path.name} - {e}")

    # 5.3 Vector indexing (Phase 6) — build embeddings for RAG
    try:
        from src.chunker import chunk_result
        from src.index.vector_index import VectorIndex

        chunks = chunk_result(result)
        if chunks:
            VectorIndex().index_chunks(chunks)
    except Exception as e:
        logger.warning(f"向量索引失败（不影响解析结果）: {path.name} - {e}")

    # 6. Fill in file info
    result.drawing.file_hash = file_hash
    result.drawing.file_size = info["file_size"]
    result.drawing.file_name = info["file_name"]
    result.drawing.file_path = info["file_path"]
    if info.get("cad_version"):
        result.drawing.cad_version = info["cad_version"]
    if info.get("cad_version_name"):
        result.drawing.cad_version_name = info["cad_version_name"]
    result.drawing.modified_time = (
        datetime.fromtimestamp(info["modified_time"]) if info.get("modified_time") else None
    )
    result.drawing.created_time = (
        datetime.fromtimestamp(info["created_time"]) if info.get("created_time") else None
    )

    # 7. Save to database
    try:
        drawing_id = repo.save_parse_result(result, overwrite=force)
    except Exception as e:
        session.rollback()
        logger.error(f"数据库保存失败: {path.name} - {e}")
        return {
            "status": "error",
            "file_name": path.name,
            "message": f"数据库保存失败: {e}",
        }
    finally:
        session.close()

    # 7.1 Register into the unified file registry (Phase 2)
    #     - archives a copy into OriginalFiles/<SourceType>/
    #     - assigns UUID file_id, dedup by SHA256, multi-source tracking
    # (summary 必须先初始化，文件登记回调会向其中写入 file_id)
    summary = {
        "status": "success",
        "drawing_id": drawing_id,
        "file_name": path.name,
        "file_type": file_type,
        "cad_version": result.drawing.cad_version,
        "cad_version_name": result.drawing.cad_version_name,
        "entity_count": result.drawing.entity_count,
        "text_count": result.drawing.text_count,
        "dimension_count": result.drawing.dimension_count,
        "layer_count": result.drawing.layer_count,
        "block_count": result.drawing.block_count,
        "data_completeness": result.drawing.data_completeness,
    }
    try:
        from src.core.file_registry import FileRegistry

        reg = FileRegistry()
        reg_result = reg.register_file(
            path,
            drawing_id=drawing_id,
            parser=result.drawing.parser or "unknown",
            parse_status=ParseStatus.SUCCESS.value,
        )
        reg.close()
        if reg_result.get("status") in ("success", "duplicate"):
            summary["file_id"] = reg_result["file_id"]
        else:
            logger.warning(f"文件登记未成功: {path.name} - {reg_result.get('message')}")
    except Exception as e:
        logger.warning(f"文件登记失败（不影响 CAD 解析结果）: {path.name} - {e}")

    # 8. Return summary
    if result.errors:
        summary["warnings"] = len(result.errors)

    if result.quality_report:
        summary["quality_report"] = result.quality_report.summary()

    logger.info(
        f"导入成功: {path.name} "
        f"(entities={summary['entity_count']}, completeness={summary['data_completeness']:.1%})"
    )

    return summary


def import_document(file_path: str | Path, force: bool = False) -> dict:
    """Import a non-CAD document (Word/Excel/PDF/CSV/...) — Phase 3.

    Pipeline: register (dedup+archive) -> parse -> write ParsedData
    -> update parse status.

    Returns:
        Dict: file_id, status, source_type, parse_status, outputs...
    """
    from src.core.file_registry import FileRegistry
    from src.normalizer.schema import ParseStatus as PS

    path = Path(file_path).resolve()
    ext = path.suffix.lower()

    # 1. Register (SHA256 dedup + archive copy)
    reg = FileRegistry()
    try:
        reg_result = reg.register_file(
            path,
            parser=DOC_PARSERS.get(ext, "document"),
            parse_status=PS.PENDING.value,
        )
        if reg_result.get("status") == "error":
            reg.close()
            return reg_result

        file_id = reg_result["file_id"]
        is_duplicate = reg_result.get("status") == "duplicate"

        # 2. Parse
        try:
            doc_result = _parse_document(path, ext)
        except Exception as e:
            reg.update_parse_status(file_id, PS.FAILED.value)
            reg.close()
            return {
                "status": "error", "file_id": file_id,
                "file_name": path.name,
                "message": f"解析异常: {e}",
            }

        if doc_result.parse_status == PS.FAILED.value:
            reg.update_parse_status(file_id, PS.FAILED.value)
            reg.close()
            return {
                "status": "failed", "file_id": file_id,
                "file_name": path.name,
                "message": "; ".join(doc_result.errors or ["解析失败"]),
            }

        doc_result.file_id = file_id

        # 3. Write ParsedData outputs (JSON/MD/TXT)
        from src.parsers.document_output import write_parsed_output

        outputs = write_parsed_output(doc_result, file_id)

        # 3.1 Store content into document_contents (Phase 5: unified FTS)
        _store_document_content(doc_result, outputs, reg)

        # 3.1.1 Document vectorization (Phase 6: RAG across formats)
        try:
            from src.core.document_rag import index_document_content

            index_document_content(file_id)
        except Exception as e:
            logger.warning(f"文档向量化失败（不影响导入）: {path.name} - {e}")

        # 3.2 Project inference (Phase 5): filename/title/path with confidence
        try:
            from src.core.project_inference import assign_project_to_file

            assign_project_to_file(
                file_id,
                file_name=path.name,
                file_path=str(path),
                doc_title=doc_result.title,
            )
        except Exception as e:
            logger.warning(f"项目推断失败（不影响导入）: {path.name} - {e}")

        # 4. Update status
        reg.update_parse_status(
            file_id,
            PS.SUCCESS.value if doc_result.parse_status == PS.SUCCESS.value
            else PS.PARTIAL.value,
            parser=doc_result.parser,
        )
    finally:
        reg.close()

    summary = {
        "status": "success",
        "file_id": file_id,
        "file_name": path.name,
        "file_type": reg_result.get("file_type"),
        "source_type": reg_result.get("source_type"),
        "parse_status": doc_result.parse_status,
        "source": doc_result.source,          # text | ocr
        "confidence": doc_result.confidence,  # OCR 置信度
        "title": doc_result.title,
        "tables": len(doc_result.tables),
        "sections": len(doc_result.sections),
        "content_len": len(doc_result.content),
    }
    if is_duplicate:
        summary["status"] = "duplicate"
        summary["message"] = "内容相同文件，已复用现有副本并重新解析"

    if outputs.get("error"):
        summary["warning"] = f"产物落盘失败: {outputs['error']}"

    logger.info(
        f"文档导入完成: {path.name} "
        f"(type={summary.get('source_type')}, status={doc_result.parse_status}, "
        f"source={doc_result.source})"
    )
    return summary


def _store_document_content(doc_result, outputs: dict, reg) -> None:
    """Persist parsed document content + rebuild FTS entry (Phase 5)."""
    from datetime import datetime

    from src.database.connection import get_session
    from src.database.models import DocumentContentModel
    from sqlalchemy import text

    session = get_session()
    try:
        rec = (
            session.query(DocumentContentModel)
            .filter(DocumentContentModel.file_id == doc_result.file_id)
            .first()
        )
        if rec is None:
            rec = DocumentContentModel(file_id=doc_result.file_id)
            session.add(rec)
        rec.source_type = doc_result.source_type
        rec.title = doc_result.title or ""
        rec.content = doc_result.content or ""
        rec.markdown = doc_result.markdown or ""
        rec.json_path = outputs.get("json_path", "")
        rec.md_path = outputs.get("md_path", "")
        rec.txt_path = outputs.get("txt_path", "")
        rec.source = doc_result.source
        rec.confidence = doc_result.confidence
        rec.updated_at = datetime.now()
        session.commit()

        # Rebuild FTS row
        session.execute(text(
            "DELETE FROM documents_fts WHERE file_id = :fid"
        ), {"fid": doc_result.file_id})
        session.execute(text(
            """
            INSERT INTO documents_fts (title, content, file_id, source_type)
            VALUES (:title, :content, :fid, :st)
            """
        ), {
            "title": rec.title or "",
            "content": rec.content or "",
            "fid": doc_result.file_id,
            "st": rec.source_type or "",
        })
        session.commit()
    except Exception as e:
        logger.warning(f"文档内容入库失败: {doc_result.file_id} - {e}")
    finally:
        session.close()


def _parse_document(path: Path, ext: str):
    """Route to the right document parser."""
    from src.parsers.excel_parser import ExcelParser
    from src.parsers.image_parser import ImageParser
    from src.parsers.pdf_parser import PDFParser
    from src.parsers.pptx_parser import PPTXParser
    from src.parsers.project_parser import ProjectParser
    from src.parsers.word_parser import WordParser

    parser_name = DOC_PARSERS.get(ext, "")
    if parser_name == "word":
        return WordParser().parse(path)
    if parser_name == "excel":
        return ExcelParser().parse(path)
    if parser_name == "pdf":
        return PDFParser().parse(path)
    if parser_name == "project":
        return ProjectParser().parse(path)
    if parser_name == "pptx":
        return PPTXParser().parse(path)
    if parser_name == "image":
        return ImageParser().parse(path)

    # Fallback: generic text extraction
    from src.normalizer.schema import ParsedDocument, ParsedSection

    doc = ParsedDocument(
        source_file=path.name, source_type="other", parser="generic")
    doc.title = path.stem
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if line:
                doc.sections.append(ParsedSection(level=0, text=line))
        doc.content = text
        doc.markdown = f"# {doc.title}\n\n```\n{text[:50000]}\n```"
    except Exception as e:
        doc.parse_status = "failed"
        doc.errors.append(f"通用文本提取失败: {e}")
    return doc


def import_directory(
    dir_path: str | Path,
    recursive: bool = True,
    force: bool = False,
) -> list[dict]:
    """Import all CAD files from a directory.
    
    Args:
        dir_path: Path to the directory.
        recursive: If True, scan subdirectories.
        force: If True, re-parse existing files.
        
    Returns:
        List of import result dicts.
    """
    path = Path(dir_path).resolve()
    if not path.is_dir():
        return [{"status": "error", "message": f"目录不存在: {path}"}]

    # Phase 3: scan CAD + documents (跳过 Office 临时锁文件 ~$xxx)
    def _is_importable(f: Path) -> bool:
        if f.name.startswith("~$"):
            return False
        return f.suffix.lower() in extensions

    extensions = {".dwg", ".dxf"} | DOC_EXTENSIONS
    if recursive:
        files = [f for f in path.rglob("*") if f.is_file() and _is_importable(f)]
    else:
        files = [f for f in path.iterdir() if f.is_file() and _is_importable(f)]

    logger.info(f"扫描到 {len(files)} 个文件 (CAD + 文档)")

    results = []
    for f in files:
        result = import_file(f, force=force)
        results.append(result)

    return results


def _select_parser(file_type: str, path: Path):
    """Select the appropriate parser for a file type."""
    if file_type == FileType.DXF.value:
        return DXFParser()
    elif file_type == FileType.DWG.value:
        return DWGParser()
    elif file_type == FileType.PDF.value:
        # Phase 3
        return None
    else:
        return None


def _unsupported_file_message(file_type: str) -> str:
    """Generate a helpful message for unsupported file types."""
    if file_type == FileType.DWG.value:
        return (
            "DWG 文件解析需要 ODA File Converter（尚未安装）。"
            "请安装 ODA File Converter 或将 DWG 转换为 DXF 格式后重试。"
            "下载地址: https://www.opendesign.com/guestfiles/oda_file_converter"
        )
    elif file_type == FileType.PDF.value:
        return "PDF 解析将在 Phase 3 实现。"
    elif file_type == FileType.IMAGE.value:
        return "图片解析将在 Phase 3+ 实现。"
    else:
        return f"不支持的文件类型: {file_type}"
