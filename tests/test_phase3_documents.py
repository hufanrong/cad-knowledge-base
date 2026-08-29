"""Unit tests for Phase 3: Word/Excel/PDF parsers + document import pipeline.

Covers:
1. Word parser: headings/body/tables/properties
2. Excel parser: sheets/headers/rows/merged cells/hidden sheets
3. CSV parser
4. PDF text extraction
5. Document import pipeline: register + archive + ParsedData outputs
6. Generic text fallback
"""

import pytest


@pytest.fixture(autouse=True)
def doc_kb(tmp_path):
    """Isolated KB for document tests."""
    from src.core.config import get_config
    from src.database.connection import init_database, reset_engine
    from src.database.models import (
        FileModel, FileSourceModel, FileVersionModel,
        ProjectModel, FileRelationModel,
    )
    from src.database.connection import get_session

    cfg = get_config()
    cfg.db_path = tmp_path / "doc_test.db"
    cfg.raw_dir = tmp_path / "OriginalFiles"
    cfg.parsed_dir = tmp_path / "ParsedData"
    cfg.ensure_directories()
    reset_engine()
    init_database()

    session = get_session()
    for m in (FileRelationModel, ProjectModel, FileVersionModel,
              FileSourceModel, FileModel):
        session.query(m).delete()
    session.commit()
    session.close()
    return tmp_path


@pytest.fixture
def docx_file(tmp_path):
    """Create a test .docx."""
    from docx import Document

    path = tmp_path / "安装方案.docx"
    doc = Document()
    doc.add_heading("冷却窑安装方案", level=1)
    doc.add_paragraph("一、工程概况")
    doc.add_paragraph("本方案适用于冷却窑设备安装。")
    t = doc.add_table(rows=3, cols=2)
    t.cell(0, 0).text = "设备"
    t.cell(0, 1).text = "数量"
    t.cell(1, 0).text = "冷却窑"
    t.cell(1, 1).text = "1台"
    t.cell(2, 0).text = "减速机"
    t.cell(2, 1).text = "2台"
    doc.core_properties.author = "张工"
    doc.save(str(path))
    return path


@pytest.fixture
def xlsx_file(tmp_path):
    """Create a test .xlsx."""
    import openpyxl

    path = tmp_path / "设备清单.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "设备清单"
    ws.append(["设备", "型号", "数量", "材料"])
    ws.append(["冷却窑", "GR-205", 1, "Q345R"])
    ws.append(["减速机", "ZQ-500", 2, "铸钢"])
    ws.merge_cells("A5:B5")
    ws["A5"] = "备注：Q355B 60mm"
    ws2 = wb.create_sheet("内部")
    ws2.append(["转速", "3.5rpm"])
    ws2.sheet_state = "hidden"
    wb.save(str(path))
    return path


@pytest.fixture
def pdf_file(tmp_path):
    """Create a text-based test PDF."""
    from reportlab.pdfgen import canvas

    path = tmp_path / "技术协议.pdf"
    c = canvas.Canvas(str(path))
    c.drawString(72, 780, "技术协议")
    c.drawString(72, 750, "材质要求 Q355B 60mm")
    c.save()
    return path


class TestWordParser:
    def test_parse_docx(self, docx_file):
        from src.parsers.word_parser import WordParser

        r = WordParser().parse(docx_file)
        assert r.parse_status == "success"
        assert r.source_type == "word"
        assert "冷却窑安装方案" in r.title or "安装方案" in r.title
        assert r.metadata.get("author") == "张工"
        # Headings captured
        assert any("工程概况" in s.text for s in r.sections)
        # Table captured
        assert len(r.tables) == 1
        assert r.tables[0].headers == ["设备", "数量"]
        assert len(r.tables[0].rows) == 2
        # Markdown generated
        assert "|" in r.markdown


class TestExcelParser:
    def test_parse_xlsx(self, xlsx_file):
        from src.parsers.excel_parser import ExcelParser

        r = ExcelParser().parse(xlsx_file)
        assert r.parse_status == "success"
        assert r.source_type == "excel"
        assert len(r.tables) == 2  # 设备清单 + 内部
        assert r.metadata.get("hidden_sheets") == ["内部"]
        main = r.tables[0]
        assert main.headers == ["设备", "型号", "数量", "材料"]
        assert len(main.rows) == 3  # 2 data rows + 1 merged-cell note row
        assert main.merged_cells, "merged cells should be detected"
        # Markdown contains merged-cell note text
        assert "Q355B" in r.markdown

    def test_parse_csv(self, tmp_path):
        import csv

        p = tmp_path / "材料.csv"
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["材料", "规格", "数量"])
            w.writerow(["钢板", "Q355B 60mm", "120"])
            w.writerow(["螺栓", "M30", "800"])

        from src.parsers.excel_parser import ExcelParser

        r = ExcelParser().parse(p)
        assert r.parse_status == "success"
        assert r.tables[0].headers == ["材料", "规格", "数量"]
        assert len(r.tables[0].rows) == 2


class TestPDFParser:
    def test_parse_text_pdf(self, pdf_file):
        from src.parsers.pdf_parser import PDFParser

        r = PDFParser().parse(pdf_file)
        assert r.parse_status == "success"
        assert r.source == "text"
        assert r.confidence == 1.0
        assert "Q355B" in r.content

    def test_scanned_pdf_marks_ocr(self, tmp_path):
        """A blank/no-text PDF must be flagged (not faked as text)."""
        from pypdf import PdfWriter

        p = tmp_path / "blank.pdf"
        w = PdfWriter()
        w.add_blank_page(width=595, height=842)
        with open(p, "wb") as f:
            w.write(f)

        from src.parsers.pdf_parser import PDFParser

        r = PDFParser().parse(p)
        # No text layer -> OCR path (may fail without tesseract, but must
        # NOT claim source=text)
        assert r.source != "text"
        assert r.parse_status in ("partial", "failed")


class TestDocumentImport:
    def test_import_word_full_pipeline(self, doc_kb, docx_file):
        """Import a docx end-to-end: register+archive+outputs."""
        from src.file_manager.importer import import_file

        r = import_file(docx_file)
        assert r["status"] == "success"
        assert r["source_type"] == "word"
        assert r["parse_status"] == "success"
        assert r["file_id"]

        # Archive copy in OriginalFiles/Word/
        from src.core.file_registry import FileRegistry

        reg = FileRegistry()
        rec = reg.get_file(r["file_id"])
        assert rec.archive_path
        assert "Word" in rec.archive_path
        assert rec.source_type == "word"
        # ParsedData outputs
        assert rec.parser == "word_parser"
        reg.close()

    def test_import_excel_and_pdf(self, doc_kb, xlsx_file, pdf_file):
        from src.file_manager.importer import import_file

        r1 = import_file(xlsx_file)
        assert r1["status"] == "success"
        assert r1["source_type"] == "excel"
        assert r1["tables"] == 2

        r2 = import_file(pdf_file)
        assert r2["status"] == "success"
        assert r2["source_type"] == "pdf"

    def test_dedup_document(self, doc_kb, docx_file):
        """Same docx imported twice -> duplicate, one archive copy,
        one source record (same path is not re-added)."""
        from src.file_manager.importer import import_file

        r1 = import_file(docx_file)
        r2 = import_file(docx_file)
        assert r2["status"] == "duplicate"
        assert r2["file_id"] == r1["file_id"]

        from src.core.file_registry import FileRegistry

        reg = FileRegistry()
        # Same original path imported twice -> only one source record
        assert len(reg.list_sources(r1["file_id"])) == 1
        reg.close()

    def test_multi_source_same_content(self, doc_kb, docx_file, tmp_path):
        """Same content at a different path -> second source record."""
        import shutil

        copy = tmp_path / "同内容副本.docx"
        shutil.copy2(docx_file, copy)

        from src.file_manager.importer import import_file
        from src.core.file_registry import FileRegistry

        r1 = import_file(docx_file)
        r2 = import_file(copy)
        assert r2["status"] == "duplicate"
        assert r2["file_id"] == r1["file_id"]

        reg = FileRegistry()
        assert len(reg.list_sources(r1["file_id"])) == 2
        reg.close()

    def test_generic_text_fallback(self, doc_kb, tmp_path):
        """TXT/JSON import through generic path."""
        p = tmp_path / "notes.txt"
        p.write_text("材料: Q355B 60mm\n数量: 120吨", encoding="utf-8")

        from src.file_manager.importer import import_file

        r = import_file(p)
        assert r["status"] == "success"
        assert r["source_type"] == "other"
        assert r["content_len"] > 0
