"""PDF document parser — Phase 3.

Two paths:
1. Text-based PDF: extract text + tables + page numbers (source=text).
2. Scanned PDF (no text layer): OCR via pytesseract if installed.
   OCR results are ALWAYS marked source=ocr + confidence — never faked
   as original text.

Output: ParsedDocument (JSON + Markdown + TXT).
"""

from __future__ import annotations

import os
from pathlib import Path

from src.normalizer.schema import (
    ParsedDocument,
    ParsedImage,
    ParsedSection,
    TableData,
)
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.parsers.pdf")

try:
    import pypdf

    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

try:
    import pdfplumber

    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False

MAX_PAGES = 300  # safety cap


class PDFParser:
    """Parse PDF into a unified ParsedDocument."""

    name = "pdf_parser"

    def parse(self, file_path: str | Path) -> ParsedDocument:
        path = Path(file_path)
        result = ParsedDocument(
            source_file=path.name,
            source_type="pdf",
            parser=self.name,
        )
        result.title = path.stem

        if not PYPDF_AVAILABLE:
            result.parse_status = "failed"
            result.errors.append("pypdf 未安装")
            return result

        # 1. Quick text extraction via pypdf
        try:
            reader = pypdf.PdfReader(str(path))
            total_pages = len(reader.pages)
            result.metadata["page_count"] = total_pages
            if reader.metadata:
                md = {}
                for k in ("title", "author", "subject", "creator", "producer"):
                    v = getattr(reader.metadata, k, None)
                    if v:
                        md[k] = str(v)
                result.metadata["properties"] = md
                if md.get("title"):
                    result.title = md["title"]
        except Exception as e:
            result.parse_status = "failed"
            result.errors.append(f"PDF 打开失败: {e}")
            return result

        # 2. Extract per-page text (pypdf first, pdfplumber for tables)
        text_pages: list[str] = []
        for i, page in enumerate(reader.pages[:MAX_PAGES]):
            try:
                t = page.extract_text() or ""
                text_pages.append(t)
            except Exception:
                text_pages.append("")

        has_text_layer = any(t.strip() for t in text_pages)

        if has_text_layer:
            # Text-based PDF
            result.source = "text"
            result.confidence = 1.0
            self._extract_text_pages(path, text_pages, result, total_pages)
        else:
            # Scanned PDF -> OCR path.
            # Mark source=ocr up-front: this file has NO text layer, so
            # any content is OCR-derived (never faked as original text).
            result.source = "ocr"
            result.confidence = 0.0
            self._try_ocr(path, result, total_pages)

        if not result.sections and not result.tables:
            result.parse_status = "partial"
            result.errors.append(
                "未提取到文本（可能为扫描版 PDF，需安装 OCR 组件）")

        result.content = self._build_content(result)
        result.markdown = self._build_markdown(result)

        logger.info(f"PDF 解析完成: {path.name} source={result.source} "
                    f"confidence={result.confidence:.2f} "
                    f"(页 {total_pages}, 段落 {len(result.sections)})")
        return result

    # ── text-based PDF ───────────────────────────────────────────────

    def _extract_text_pages(self, path, text_pages, result, total_pages):
        table_count = 0
        if PDFPLUMBER_AVAILABLE:
            try:
                with pdfplumber.open(str(path)) as pdf:
                    for i, page in enumerate(pdf.pages[:MAX_PAGES]):
                        # Tables first (page number attached)
                        for t in page.extract_tables():
                            if not t:
                                continue
                            headers = [str(c or "") for c in (t[0] or [])]
                            rows = [
                                [str(c or "") for c in (r or [])]
                                for r in t[1:]
                            ]
                            result.tables.append(TableData(
                                sheet=f"第{i + 1}页",
                                headers=headers, rows=rows))
                            table_count += 1
            except Exception as e:
                logger.warning(f"pdfplumber 表格提取失败: {e}")

        for i, text in enumerate(text_pages):
            text = text.strip()
            if not text:
                continue
            # Split into paragraphs
            for para in text.split("\n"):
                para = para.strip()
                if not para:
                    continue
                if self._looks_like_heading(para):
                    result.sections.append(ParsedSection(
                        level=1, title=para, text=para, page=i + 1))
                else:
                    result.sections.append(ParsedSection(
                        level=0, text=para, page=i + 1))

    @staticmethod
    def _looks_like_heading(text: str) -> bool:
        """Heuristic: short line ending with numbers or containing 图/表/章."""
        t = text.strip()
        if len(t) > 30:
            return False
        if t.startswith(("第", "章", "节", "一、", "二、", "三、", "四、",
                          "五、", "六、", "七、", "八、", "九、", "十、",
                          "1.", "2.", "3.", "4.", "5.", "6.", "7.",
                          "8.", "9.", "（一）", "（二）", "（三）")):
            return True
        return False

    # ── OCR path ─────────────────────────────────────────────────────

    def _try_ocr(self, path, result, total_pages):
        """OCR scanned PDF pages. Marks source=ocr + confidence."""
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            result.errors.append(
                "扫描版 PDF：pytesseract 未安装，无法 OCR。"
                "保留文件副本，解析标记为待处理。")
            return

        # winget 安装的 Tesseract 可能不在 PATH 中，显式指定
        for cand in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ):
            if os.path.exists(cand):
                pytesseract.pytesseract.tesseract_cmd = cand
                break

        try:
            import fitz  # PyMuPDF
        except ImportError:
            result.errors.append(
                "扫描版 PDF：PyMuPDF 未安装，无法渲染页面。")
            return

        ocr_texts = []
        confidences = []
        # 用户级 tessdata（无需管理员权限）：C:/Users/hufanrong/tessdata
        user_tessdata = Path.home() / "tessdata"
        if user_tessdata.exists():
            os.environ.setdefault("TESSDATA_PREFIX", str(user_tessdata))
        for i in range(min(total_pages, 20)):  # cap OCR pages
            try:
                doc = fitz.open(str(path))
                page = doc[i]
                pix = page.get_pixmap(dpi=200)
                import io
                from PIL import Image

                img = Image.open(io.BytesIO(pix.tobytes("png")))
                data = pytesseract.image_to_data(
                    img, lang="chi_sim+eng", output_type=pytesseract.Output.DICT)
                page_text = []
                conf = []
                for j, word in enumerate(data["text"]):
                    if word and word.strip():
                        page_text.append(word)
                        conf.append(int(data["conf"][j]) / 100.0)
                if page_text:
                    ocr_texts.append(" ".join(page_text))
                    confidences.append(
                        sum(conf) / len(conf) if conf else 0.5)
                doc.close()
            except Exception as e:
                logger.warning(f"OCR 第 {i + 1} 页失败: {e}")
                break

        if ocr_texts:
            result.source = "ocr"
            result.confidence = round(sum(confidences) / len(confidences), 3)
            for i, t in enumerate(ocr_texts):
                result.sections.append(ParsedSection(
                    level=0, text=t, page=i + 1))
        else:
            result.errors.append("OCR 未提取到内容")

    # ── output ───────────────────────────────────────────────────────

    def _build_content(self, result: ParsedDocument) -> str:
        lines = [result.title]
        for sec in result.sections:
            if sec.level > 0:
                lines.append(f"## {sec.title}")
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
        if result.source == "ocr":
            lines.append(
                f"\n> ⚠️ 本文件为 OCR 识别内容 (置信度 {result.confidence:.0%})")
        for sec in result.sections:
            if sec.level > 0:
                lines.append(f"## {sec.title}")
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


def parse_pdf(file_path: str | Path) -> ParsedDocument:
    """Convenience wrapper."""
    return PDFParser().parse(file_path)
