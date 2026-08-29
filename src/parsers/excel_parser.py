"""Excel document parser (.xlsx/.xlsm/.csv) — Phase 3.

Extracts: workbook sheets, headers, cells, merged cells, formulas,
hidden sheets, sheet names. Keeps structured data (workbook/sheet/
headers/rows) AND generates a Markdown version for LLM reading.

Output: ParsedDocument with structured tables + markdown.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from src.normalizer.schema import ParsedDocument, TableData
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.parsers.excel")

try:
    import openpyxl

    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

MAX_ROWS_PER_SHEET = 5000   # safety cap per sheet
MAX_COLS = 200


class ExcelParser:
    """Parse xlsx/xlsm/csv into a unified ParsedDocument."""

    name = "excel_parser"

    def parse(self, file_path: str | Path) -> ParsedDocument:
        path = Path(file_path)
        result = ParsedDocument(
            source_file=path.name,
            source_type="excel",
            parser=self.name,
        )
        result.title = path.stem

        ext = path.suffix.lower()
        if ext == ".csv":
            self._parse_csv(path, result)
        elif ext == ".xls":
            self._parse_xls(path, result)   # 旧格式 via xlrd
        else:
            self._parse_xlsx(path, result)

        if not result.tables:
            result.parse_status = "partial"
            result.errors.append("未提取到有效表格数据")

        result.content = self._build_content(result)
        result.markdown = self._build_markdown(result)

        logger.info(f"Excel 解析完成: {path.name} "
                    f"(表 {len(result.tables)}, 行 "
                    f"{sum(len(t.rows) for t in result.tables)})")
        return result

    # ── xls (旧格式) ─────────────────────────────────────────────────

    def _parse_xls(self, path: Path, result: ParsedDocument):
        """Parse legacy .xls binary format via xlrd."""
        try:
            import xlrd
        except ImportError:
            result.parse_status = "failed"
            result.errors.append("xlrd 未安装，无法解析 .xls 旧格式")
            return
        try:
            wb = xlrd.open_workbook(str(path), on_demand=True)
        except Exception as e:
            result.parse_status = "failed"
            result.errors.append(f"xlrd 打开失败: {e}")
            return

        sheet_names = wb.sheet_names()
        result.metadata["sheet_names"] = sheet_names
        result.metadata["file_format"] = "xls(binary)"
        hidden = []
        for name in sheet_names:
            sh = wb.sheet_by_name(name)
            if sh.visibility == 1:      # 0=visible 1=hidden 2=very-hidden
                hidden.append(name)
        result.metadata["hidden_sheets"] = hidden

        for name in sheet_names:
            sh = wb.sheet_by_name(name)
            if not sh.nrows:
                continue
            rows_data = []
            for r in range(sh.nrows):
                row = []
                for c in range(sh.ncols):
                    # xlrd 空单元格返回 0.0，须按类型判断为空白
                    ctype = sh.cell_type(r, c)
                    if ctype in (xlrd.XL_CELL_BLANK, xlrd.XL_CELL_EMPTY):
                        row.append("")
                        continue
                    v = sh.cell_value(r, c)
                    if isinstance(v, float) and v == int(v):
                        v = int(v)          # 1.0 -> 1
                    row.append("" if v is None else str(v).strip())
                rows_data.append(row)
            # 过滤全空行
            rows_data = [r for r in rows_data if any(c for c in r)]
            if not rows_data:
                continue
            headers = rows_data[0]
            body = rows_data[1:]
            result.tables.append(TableData(
                sheet=name, headers=headers, rows=body,
                merged_cells=[],   # xlrd 兼容性：跳过合并单元格检测
            ))
        logger.info(f".xls 解析: {path.name} -> {len(result.tables)} 个表")
    # ── xlsx/xlsm ────────────────────────────────────────────────────

    def _parse_xlsx(self, path: Path, result: ParsedDocument):
        if not OPENPYXL_AVAILABLE:
            result.parse_status = "failed"
            result.errors.append("openpyxl 未安装")
            return
        try:
            wb = openpyxl.load_workbook(
                path, data_only=True, read_only=False)
        except Exception as e:
            result.parse_status = "failed"
            result.errors.append(f"打开失败: {e}")
            return

        result.metadata["workbook"] = path.stem
        result.metadata["sheet_names"] = wb.sheetnames

        for ws in wb.worksheets:
            sheet_name = ws.title
            is_hidden = ws.sheet_state != "visible"
            rows_data = []
            for row in ws.iter_rows(
                min_row=1, max_col=min(ws.max_column or 0, MAX_COLS),
                max_row=min(ws.max_row or 0, MAX_ROWS_PER_SHEET),
            ):
                cells = []
                for cell in row:
                    val = cell.value
                    if val is None:
                        cells.append("")
                    else:
                        cells.append(str(val))
                rows_data.append(cells)

            if not rows_data:
                continue

            # Header = first non-empty row (prefer row 1 if it has any text)
            headers = rows_data[0]
            # Skip fully-empty body rows (merged-cell remnants etc.)
            body = [r for r in rows_data[1:] if any(str(c).strip() for c in r)]

            td = TableData(
                sheet=sheet_name,
                headers=headers,
                rows=body,
                merged_cells=self._merged_cells(ws),
            )
            if is_hidden:
                result.metadata.setdefault("hidden_sheets", []).append(sheet_name)
            result.tables.append(td)

        wb.close()

    def _merged_cells(self, ws) -> list[list[dict]]:
        merged = []
        for mc in list(ws.merged_cells.ranges)[:50]:
            merged.append({
                "min_row": mc.min_row, "max_row": mc.max_row,
                "min_col": mc.min_col, "max_col": mc.max_col,
            })
        return merged

    # ── csv ──────────────────────────────────────────────────────────

    def _parse_csv(self, path: Path, result: ParsedDocument):
        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
                reader = csv.reader(f)
                rows = [r for r in reader][:MAX_ROWS_PER_SHEET]
        except Exception as e:
            result.parse_status = "failed"
            result.errors.append(f"CSV 读取失败: {e}")
            return

        if not rows:
            return
        headers = rows[0]
        body = rows[1:]
        result.tables.append(TableData(
            sheet=path.stem, headers=headers, rows=body))

    # ── output ───────────────────────────────────────────────────────

    def _build_content(self, result: ParsedDocument) -> str:
        lines = [result.title]
        for td in result.tables:
            lines.append(f"[Sheet: {td.sheet}]")
            if td.headers:
                lines.append(" | ".join(td.headers))
            for row in td.rows:
                lines.append(" | ".join(row))
        return "\n".join(lines)

    def _build_markdown(self, result: ParsedDocument) -> str:
        lines = [f"# {result.title}"]
        hidden = result.metadata.get("hidden_sheets", [])
        if hidden:
            lines.append(f"\n> 隐藏工作表: {', '.join(hidden)}")
        for td in result.tables:
            lines.append(f"\n## 工作表: {td.sheet}")
            if td.headers:
                h = [str(h) for h in td.headers]
                lines.append("| " + " | ".join(h) + " |")
                lines.append("|" + "|".join(["---"] * len(h)) + "|")
            for row in td.rows:
                r = [str(c) for c in row]
                if len(r) < len(td.headers):
                    r += [""] * (len(td.headers) - len(r))
                lines.append("| " + " | ".join(r[:len(td.headers)]) + " |")
        return "\n".join(lines)


def parse_excel(file_path: str | Path) -> ParsedDocument:
    """Convenience wrapper."""
    return ExcelParser().parse(file_path)
