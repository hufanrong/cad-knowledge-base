"""PowerPoint (.pptx) parser — Phase 4.

Extracts: slide text, tables, notes, layout/theme hints.

Output: ParsedDocument.
"""

from __future__ import annotations

from pathlib import Path

from src.normalizer.schema import ParsedDocument, ParsedSection, TableData
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.parsers.pptx")

try:
    from pptx import Presentation

    PPTX_AVAILABLE = True
except ImportError:
    PPTX_AVAILABLE = False


class PPTXParser:
    """Parse .pptx into a unified ParsedDocument."""

    name = "pptx_parser"

    def parse(self, file_path: str | Path) -> ParsedDocument:
        path = Path(file_path)
        result = ParsedDocument(
            source_file=path.name,
            source_type="other",   # presentation 归 other（无专属 SourceType）
            parser=self.name,
        )
        result.title = path.stem

        if not PPTX_AVAILABLE:
            result.parse_status = "failed"
            result.errors.append("python-pptx 未安装")
            return result

        try:
            prs = Presentation(str(path))
        except Exception as e:
            result.parse_status = "failed"
            result.errors.append(f"打开失败: {e}")
            return result

        result.metadata["slide_count"] = len(prs.slides)

        for si, slide in enumerate(prs.slides, start=1):
            slide_texts = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        t = "".join(run.text for run in para.runs).strip()
                        if t:
                            slide_texts.append(t)
                if shape.has_table:
                    table = shape.table
                    headers = [c.text.strip() for c in table.rows[0].cells]
                    rows = [
                        [c.text.strip() for c in row.cells]
                        for row in table.rows[1:]
                    ]
                    result.tables.append(TableData(
                        sheet=f"第{si}页表格", headers=headers, rows=rows))

            if slide_texts:
                # First non-empty line as slide heading
                result.sections.append(ParsedSection(
                    level=1, title=f"幻灯片 {si}", text="；".join(slide_texts),
                ))

            # Notes
            try:
                if slide.has_notes_slide:
                    notes = slide.notes_slide.notes_text_frame.text.strip()
                    if notes:
                        result.sections.append(ParsedSection(
                            level=0, text=f"[备注] {notes}"))
            except Exception:
                pass

        if not result.sections and not result.tables:
            result.parse_status = "partial"
            result.errors.append("未提取到内容")

        result.content = self._build_content(result)
        result.markdown = self._build_markdown(result)

        logger.info(f"PPTX 解析完成: {path.name} (页 {len(prs.slides)})")
        return result

    def _build_content(self, result: ParsedDocument) -> str:
        lines = [result.title]
        for sec in result.sections:
            if sec.level > 0:
                # text contains slide heading + body joined by '；'
                lines.append(f"## {sec.text}")
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
        for sec in result.sections:
            if sec.level > 0:
                lines.append(f"\n## {sec.title}")
                if sec.text and len(sec.text) > len(sec.title or ""):
                    lines.append(sec.text)
            elif sec.text:
                lines.append(sec.text)
        for td in result.tables:
            lines.append("\n## 表格")
            if td.headers:
                lines.append("| " + " | ".join(td.headers) + " |")
                lines.append("|" + "|".join(["---"] * len(td.headers)) + "|")
            for row in td.rows:
                lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)


def parse_pptx(file_path: str | Path) -> ParsedDocument:
    """Convenience wrapper."""
    return PPTXParser().parse(file_path)
