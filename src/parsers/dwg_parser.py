"""DWG Parser based on ODA File Converter + ezdxf.

DWG files are Autodesk's proprietary binary format; ezdxf cannot read them
directly. This parser:

1. Uses ODA File Converter to convert DWG -> DXF (in a temp directory)
2. Reuses DXFParser to parse the resulting DXF into the unified schema
3. Adjusts metadata so it points back to the original DWG file

Data provenance is preserved: the parsing itself still tags everything as
DataTier.NORMALIZED (values unchanged from the converted DXF). The fact
that the file passed through ODA conversion is recorded in `parser` and
`parser_version` fields on the Drawing.

If ODA File Converter is not installed, parse() returns a FAILED result
with a clear, actionable error message (no data is fabricated).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.normalizer.schema import FileType, ParseResult, ParseStatus
from src.parsers.base_parser import BaseParser
from src.parsers.dxf_parser import DXFParser
from src.parsers.oda_converter import ODAConverter, is_oda_available
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.parsers.dwg")

ODA_VERSION = "27.1"


class DWGParser(BaseParser):
    """Parse DWG files via ODA File Converter + ezdxf."""

    def __init__(self, oda_converter: ODAConverter | None = None):
        self._dxf_parser = DXFParser()
        self._oda = oda_converter or ODAConverter()

    @property
    def name(self) -> str:
        if self._oda.is_available():
            return "oda+ezdxf"
        from src.parsers.autocad_com import is_autocad_available

        if is_autocad_available():
            return "autocad_com+ezdxf"
        return "oda-missing+ezdxf"

    @property
    def version(self) -> str:
        if self._oda.is_available():
            return f"oda-{ODA_VERSION}+ezdxf"
        return "oda-missing+ezdxf"

    @property
    def supported_types(self) -> list[str]:
        return ["dwg"]

    def can_parse(self, file_path: str | Path) -> bool:
        path = Path(file_path)
        return path.suffix.lower() == ".dwg"

    def parse(self, file_path: str | Path) -> ParseResult:
        """Parse a DWG file into the unified schema.

        Returns:
            ParseResult. On failure (no ODA, conversion error, etc.)
            drawing.parse_status is FAILED and errors are populated.
            No data is fabricated — unknown/unreadable parts are skipped.
        """
        path = Path(file_path)
        logger.info(f"开始解析 DWG: {path.name}")

        # 1. Determine conversion backend: ODA (primary) or AutoCAD COM (fallback)
        oda_ok = self._oda.is_available()
        autocad_ok = False
        if not oda_ok:
            from src.parsers.autocad_com import is_autocad_available

            autocad_ok = is_autocad_available()
            if autocad_ok:
                logger.info("ODA 不可用，使用 AutoCAD COM 备选路径")

        if not oda_ok and not autocad_ok:
            logger.error("ODA File Converter 与 AutoCAD COM 均不可用，无法解析 DWG")
            result = ParseResult()
            result.drawing.file_name = path.name
            result.drawing.file_path = str(path.absolute())
            result.drawing.file_type = FileType.DWG
            result.drawing.parser = self.name
            result.drawing.parser_version = self.version
            result.drawing.parse_status = ParseStatus.FAILED
            result.errors.append({
                "operation": "oda_check",
                "error": (
                    "ODA File Converter 未安装且 AutoCAD COM 不可用。请从 "
                    "https://www.opendesign.com/guestfiles/oda_file_converter "
                    "下载安装（非商业用途免费）后重试。"
                ),
                "file": str(path),
            })
            return result

        # 2. Convert DWG -> DXF in a temp directory
        try:
            with tempfile.TemporaryDirectory(prefix="cadkb_dwg_") as tmp_dir:
                dxf_path = None
                if oda_ok:
                    dxf_path = self._oda.convert_dwg_to_dxf(
                        dwg_path=path,
                        output_dir=tmp_dir,
                        output_version="ACAD2018",
                        audit=True,
                    )
                else:
                    from src.parsers.autocad_com import convert_dwg_to_dxf

                    dxf_path = convert_dwg_to_dxf(
                        dwg_path=path,
                        output_dir=tmp_dir,
                    )

                if dxf_path is None:
                    raise RuntimeError(f"转换失败: {path.name}")

                logger.info(f"DWG 已转换为 DXF: {dxf_path.name}")

                # 3. Parse the DXF with the existing DXF parser
                result = self._dxf_parser.parse(dxf_path)
        except Exception as e:
            logger.error(f"DWG 解析失败: {path.name} - {e}")
            result = ParseResult()
            result.drawing.file_name = path.name
            result.drawing.file_path = str(path.absolute())
            result.drawing.file_type = FileType.DWG
            result.drawing.parser = self.name
            result.drawing.parser_version = self.version
            result.drawing.parse_status = ParseStatus.FAILED
            result.errors.append({
                "operation": "dwg_parse",
                "error": str(e),
                "file": str(path),
            })
            return result

        # 4. Fix metadata to reference the ORIGINAL DWG, not the temp DXF
        result.drawing.file_name = path.name
        result.drawing.file_path = str(path.absolute())
        result.drawing.file_type = FileType.DWG
        result.drawing.parser = self.name
        result.drawing.parser_version = self.version

        # Re-read version info from the ORIGINAL DWG header. The converted
        # DXF is always written as ACAD2018, so its $ACADVER would be wrong.
        from src.file_manager.version_detector import detect_dwg_version

        dwg_version, dwg_version_name = detect_dwg_version(path)
        if dwg_version:
            result.drawing.cad_version = dwg_version
            result.drawing.cad_version_name = dwg_version_name

        # Update entity/dimension/text layer references to the DWG source
        # (the DXF parser already set drawing_id via repository, but the
        # source paths inside entities point to the temp DXF; keep them,
        # since they refer to the converted representation.)
        return result
