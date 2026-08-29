"""AutoCAD COM fallback parser — AutoCAD COM 备选解析路径 (Phase 8).

If AutoCAD is installed (and its COM interface is available), this module
can open a DWG and save it as DXF as a fallback when ODA File Converter
is unavailable or fails.

Design:
- Detection: probe the AutoCAD COM ProgID (AutoCAD.Application).
- If AutoCAD is not installed, `is_autocad_available()` returns False and
  all operations return errors gracefully — no crash, no fabrication.
- Uses comtypes (lightweight, Apache-2.0); falls back to pywin32 if
  comtypes is missing.

NOTE: Opening AutoCAD is slow and heavyweight; this is strictly a
fallback path. ODA remains the primary converter.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.utils.logger import setup_logger

logger = setup_logger("cadkb.parsers.autocad_com")

# Whether we've probed the COM environment yet
_cache_available: bool | None = None
_cache_reason: str = ""


def _com_module():
    """Return the COM module (comtypes or pywin32 win32com)."""
    try:
        import comtypes.client  # noqa: F401

        return "comtypes"
    except ImportError:
        pass
    try:
        import win32com.client  # noqa: F401

        return "pywin32"
    except ImportError:
        pass
    return None


def is_autocad_available() -> bool:
    """Check whether AutoCAD's COM interface can be used.

    Returns:
        True if AutoCAD is installed and COM is reachable.
    """
    global _cache_available, _cache_reason
    if _cache_available is not None:
        return _cache_available

    module = _com_module()
    if module is None:
        _cache_available = False
        _cache_reason = "comtypes/pywin32 未安装"
        return False

    try:
        if module == "comtypes":
            import comtypes.client

            comtypes.client.GetActiveObject("AutoCAD.Application")
        else:
            import win32com.client

            win32com.client.Dispatch("AutoCAD.Application")
        _cache_available = True
        _cache_reason = "ok"
        return True
    except Exception as e:
        _cache_available = False
        _cache_reason = str(e)
        logger.info(f"AutoCAD COM 不可用: {e}")
        return False


def autocad_unavailable_reason() -> str:
    """Return why AutoCAD COM is unavailable (for logging)."""
    if _cache_available is None:
        is_autocad_available()
    return _cache_reason


def convert_dwg_to_dxf(
    dwg_path: str | Path,
    output_dir: str | Path | None = None,
) -> Path | None:
    """Use AutoCAD COM to open a DWG and save it as DXF.

    Args:
        dwg_path: Path to the DWG file.
        output_dir: Directory for the output DXF. Defaults to a temp dir.

    Returns:
        Path to the generated DXF, or None on failure.
    """
    dwg = Path(dwg_path)
    if not dwg.exists():
        logger.error(f"DWG 不存在: {dwg}")
        return None

    if not is_autocad_available():
        logger.warning(f"AutoCAD COM 不可用（{autocad_unavailable_reason()}），无法转换")
        return None

    out_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="cadkb_acad_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dxf = out_dir / (dwg.stem + ".dxf")

    module = _com_module()
    try:
        if module == "comtypes":
            import comtypes.client

            acad = comtypes.client.GetActiveObject("AutoCAD.Application")
        else:
            import win32com.client

            acad = win32com.client.Dispatch("AutoCAD.Application")

        doc = acad.Documents.Open(str(dwg.resolve()))
        try:
            # acadSaveAs dxf format code: ac2018_dxf = 61? For safety use 12 (acR12_dxf)
            # Format codes: 1=acR12_dxf, 8=ac2000_dxf, 12=ac2004_dxf,
            # 13=ac2007_dxf, 16=ac2010_dxf, 24=ac2018_dxf, etc.
            doc.SaveAs(str(out_dxf), 24)  # ac2018_dxf
        finally:
            doc.Close(False)
    except Exception as e:
        logger.warning(f"AutoCAD COM 转换失败: {e}")
        return None

    if out_dxf.exists() and out_dxf.stat().st_size > 0:
        logger.info(f"AutoCAD COM 转换成功: {dwg.name} -> {out_dxf.name}")
        return out_dxf
    logger.error(f"AutoCAD COM 转换未产生输出: {dwg.name}")
    return None
