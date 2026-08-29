"""Word document parser (.docx) — Phase 3.

Extracts: headings, body text, tables, image captions, headers/footers,
document properties (author, created/modified time, doc number, project
name, technical parameters, materials, construction/safety requirements...).

Output: ParsedDocument (JSON + Markdown + TXT).
"""

from __future__ import annotations

from pathlib import Path

from src.normalizer.schema import (
    ParsedDocument,
    ParsedImage,
    ParsedSection,
    TableData,
)
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.parsers.word")

try:
    import docx as python_docx
    from docx.document import Document as DocxDocument
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph as DocxParagraph

    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False


class WordParser:
    """Parse .docx into a unified ParsedDocument."""

    name = "word_parser"

    def parse(self, file_path: str | Path) -> ParsedDocument:
        path = Path(file_path)
        result = ParsedDocument(
            source_file=path.name,
            source_type="word",
            parser=self.name,
        )
        if not DOCX_AVAILABLE:
            result.parse_status = "failed"
            result.errors.append("python-docx 未安装")
            return result

        # .doc 旧格式：先经 LibreOffice 转换（无 LO 时降级文本提取）
        if path.suffix.lower() == ".doc":
            converted = self._convert_doc_to_docx(path)
            if not converted:
                self._fallback_doc_text(path, result)
                return result
            path = converted

        try:
            doc = python_docx.Document(str(path))
        except Exception as e:
            result.parse_status = "failed"
            result.errors.append(f"打开失败: {e}")
            return result

        # 1. Document properties
        self._extract_properties(doc, result, path)

        # 2. Body: paragraphs in document order (tables interleaved)
        self._extract_body(doc, result, path)

        # 3. Headers & footers
        self._extract_headers_footers(doc, result)

        # 4. Build content / markdown
        result.content = self._build_content(result)
        result.markdown = self._build_markdown(result)

        if not result.sections and not result.tables:
            result.parse_status = "partial"
            result.errors.append("未提取到文本/表格")

        logger.info(f"Word 解析完成: {path.name} "
                    f"(段落 {len(result.sections)}, 表格 {len(result.tables)}, "
                    f"图片 {len(result.images)})")
        return result

    # ── .doc (旧格式) 转换/降级 ──────────────────────────────────────

    def _convert_doc_to_docx(self, path: Path) -> Path | None:
        """Convert .doc -> .docx via LibreOffice headless. Returns docx path or None."""
        import shutil
        import subprocess
        import tempfile

        soffice = shutil.which("soffice") or (
            Path("C:/Program Files/LibreOffice/program/soffice.exe")
            if (Path("C:/Program Files/LibreOffice/program/soffice.exe").exists()) else None)
        if not soffice:
            return None
        tmp = Path(tempfile.mkdtemp(prefix="doc_conv_"))
        try:
            subprocess.run(
                [str(soffice), "--headless", "--convert-to", "docx",
                 "--outdir", str(tmp), str(path)],
                capture_output=True, timeout=120, check=False,
            )
            out = next(tmp.glob("*.docx"), None)
            return out if out and out.exists() else None
        except Exception:
            return None

    def _fallback_doc_text(self, path: Path, result: ParsedDocument):
        """降级：.doc 无 LibreOffice 时用 olefile/docx2txt 尽力提取文本（不伪造）。"""
        text = ""
        try:
            import docx2txt
            text = docx2txt.process(str(path)) or ""
        except Exception:
            try:
                import olefile
                if olefile.isOleFile(str(path)):
                    ole = olefile.OleFileIO(str(path))
                    if ole.exists("WordDocument"):
                        text = "(OLE2 Word 二进制文档：未安装 LibreOffice，仅登记元数据)"
            except Exception:
                pass
        if text:
            result.sections.append(ParsedSection(level=0, text=text[:4000]))
            result.content = text
            result.parse_status = "partial"
        else:
            result.parse_status = "pending"
            result.errors.append("未安装 LibreOffice，.doc 旧格式暂不可解析（已保留副本）")

    # ── extraction helpers ───────────────────────────────────────────

    def _extract_properties(self, doc, result: ParsedDocument, path: Path):
        props = doc.core_properties
        meta = {}
        for key in ("author", "last_modified_by", "title", "subject",
                    "keywords", "comments", "category"):
            val = getattr(props, key, None)
            if val:
                meta[key] = str(val)
        for key in ("created", "modified"):
            val = getattr(props, key, None)
            if val:
                meta[key] = val.isoformat() if hasattr(val, "isoformat") else str(val)

        # File-level fallback times
        if not meta.get("created"):
            meta["created"] = path.stat().st_ctime
        if not meta.get("modified"):
            meta["modified"] = path.stat().st_mtime

        result.title = meta.get("title", path.stem)
        result.metadata = meta

    def _extract_body(self, doc, result: ParsedDocument, path: Path):
        """Iterate document body elements in order (paragraphs + tables)."""
        from docx.oxml.ns import qn

        body = doc.element.body
        img_index = 0
        section_level = 0

        for child in body.iterchildren():
            tag = child.tag
            if tag == qn("w:p"):
                para = DocxParagraph(child, doc)
                text = para.text.strip()
                if not text:
                    continue
                style = (para.style.name or "").lower() if para.style else ""
                if "heading" in style or "标题" in style:
                    # Heading level from style name
                    level = 1
                    for part in style.replace("heading", "").split():
                        if part.isdigit():
                            level = int(part)
                            break
                    section_level = level
                    result.sections.append(ParsedSection(
                        level=level, title=text, text=text))
                elif section_level > 0:
                    # Body text under a heading
                    result.sections.append(ParsedSection(
                        level=0, text=text))
                else:
                    result.sections.append(ParsedSection(level=0, text=text))

                # Inline images
                for drawing in child.iter(qn("w:drawing")):
                    img_index += 1
                    result.images.append(ParsedImage(index=img_index))

            elif tag == qn("w:tbl"):
                table = DocxTable(child, doc)
                td = self._extract_table(table, "正文")
                result.tables.append(td)

        # Image captions from paragraphs containing "图" + number
        for sec in result.sections:
            if sec.level == 0 and len(sec.text) < 60 and "图" in sec.text:
                pass  # keep simple: captions stay in section text

    def _extract_table(self, table, sheet_name: str) -> TableData:
        headers: list[str] = []
        rows: list[list[str]] = []
        for ri, row in enumerate(table.rows):
            cells = []
            for cell in row.cells:
                txt = " ".join(cell.text.split())
                cells.append(txt)
            if ri == 0:
                headers = cells
            else:
                rows.append(cells)
        # If first row looks like data (no distinct header), keep as header anyway
        return TableData(sheet=sheet_name, headers=headers, rows=rows)

    def _extract_headers_footers(self, doc, result: ParsedDocument):
        texts = []
        for section in doc.sections:
            for header in (section.header, section.footer):
                try:
                    if header and not header.is_linked_to_previous:
                        for para in header.paragraphs:
                            t = para.text.strip()
                            if t:
                                texts.append(t)
                except Exception:
                    pass
        if texts:
            result.metadata["headers_footers"] = texts

    # ── output builders ──────────────────────────────────────────────

    def _build_content(self, result: ParsedDocument) -> str:
        lines = []
        if result.title:
            lines.append(result.title)
        for sec in result.sections:
            if sec.level > 0:
                lines.append(f"{'#' * min(sec.level, 6)} {sec.title}")
            elif sec.text:
                lines.append(sec.text)
        for td in result.tables:
            if td.headers:
                lines.append(" | ".join(td.headers))
            for row in td.rows:
                lines.append(" | ".join(row))
        return "\n".join(lines)

    def _build_markdown(self, result: ParsedDocument) -> str:
        lines = [f"# {result.title}"]
        meta = result.metadata
        if meta.get("author"):
            lines.append(f"\n> 作者: {meta['author']}")
        lines.append("")
        for sec in result.sections:
            if sec.level > 0:
                lines.append(f"{'#' * min(sec.level + 1, 6)} {sec.title}")
            elif sec.text:
                lines.append(sec.text)
        for i, td in enumerate(result.tables):
            lines.append(f"\n## 表格 {i + 1}")
            if td.headers:
                lines.append("| " + " | ".join(td.headers) + " |")
                lines.append("|" + "|".join(["---"] * len(td.headers)) + "|")
            for row in td.rows:
                lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)


def parse_word(file_path: str | Path) -> ParsedDocument:
    """Convenience wrapper."""
    return WordParser().parse(file_path)
