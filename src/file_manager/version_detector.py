"""File type and CAD version detection.

Phase 2 expansion: multi-format detection (extension + magic bytes).
"""

import os
import zipfile
from pathlib import Path

from src.normalizer.schema import DWG_VERSION_MAP, FileType


# ─── Magic bytes (multi-format) ──────────────────────────────────────
# (prefix bytes, FileType); None means "need deeper inspection"
MAGIC_BYTES: list[tuple[bytes, FileType | None]] = [
    (b"\x25\x50\x44\x46", FileType.PDF),            # %PDF
    (b"\xff\xd8\xff", FileType.IMAGE),              # JPEG
    (b"\x89\x50\x4e\x47", FileType.IMAGE),          # PNG
    (b"GIF8", FileType.IMAGE),                      # GIF
    (b"BM", FileType.IMAGE),                        # BMP
    (b"II*\x00", FileType.IMAGE),                   # TIFF little-endian
    (b"MM\x00*", FileType.IMAGE),                   # TIFF big-endian
    (b"\xef\xbb\xbf", FileType.TXT),                # UTF-8 BOM text
    (b"AC", FileType.DWG),                          # DWG header (AC1xxx/AC10xx)
    (b"PK", None),                                  # ZIP container -> docx/xlsx/pptx...
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", None),    # OLE2 -> doc/xls/ppt/mpp
]

# OLE2 container: check embedded stream signatures (at offset 0x200+)
OLE2_SIGNATURES: list[tuple[bytes, FileType]] = [
    (b"\xec\xa5\xc1\x00", FileType.DOC),            # Word Document stream
    (b"\x09\x08\x10\x00\x00\x06\x05\x00", FileType.XLS),   # Workbook stream
    (b"\xfd\xff\xff\xff", FileType.XLS),            # Workbook (older)
    (b"\x0f\x00\x00\x00", FileType.PPT),            # PowerPoint Document
    (b"\xa0\x46\x1d\xf0", FileType.PPT),            # PowerPoint (95)
    (b"\xfd\xff\xff\xff\x0f\x00\x00\x00", FileType.PPT),
]


def detect_file_type(file_path: str | Path) -> FileType:
    """Detect file type from extension + magic bytes.

    Priority: real content signature first, extension as fallback,
    so disguised files (e.g. .jpg that is actually a ZIP) are caught.

    Args:
        file_path: Path to the file.

    Returns:
        FileType enum value.
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    # 1. Magic bytes detection (content-based)
    try:
        with open(path, "rb") as f:
            header = f.read(16)
    except Exception:
        return FileType.UNKNOWN

    for prefix, ftype in MAGIC_BYTES:
        if header.startswith(prefix):
            if ftype is not None:
                return ftype
            # ZIP container -> inspect internal entries
            if prefix == b"PK":
                return _detect_zip_type(path)
            # OLE2 container -> inspect embedded streams
            if prefix == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                return _detect_ole2_type(path)

    # 2. Extension fallback
    if ext == ".dwg":
        return FileType.DWG
    elif ext == ".dxf":
        return FileType.DXF
    elif ext in (".dwt",):
        return FileType.DWT
    elif ext in (".dws",):
        return FileType.DWS
    elif ext == ".pdf":
        return FileType.PDF
    elif ext in (".docx",):
        return FileType.DOCX
    elif ext == ".doc":
        return FileType.DOC
    elif ext in (".xlsx",):
        return FileType.XLSX
    elif ext == ".xlsm":
        return FileType.XLSM
    elif ext == ".xls":
        return FileType.XLS
    elif ext == ".csv":
        return FileType.CSV
    elif ext in (".pptx",):
        return FileType.PPTX
    elif ext == ".ppt":
        return FileType.PPT
    elif ext == ".mpp":
        return FileType.MPP
    elif ext == ".rtf":
        return FileType.RTF
    elif ext == ".txt":
        return FileType.TXT
    elif ext == ".xml":
        return FileType.XML
    elif ext == ".json":
        return FileType.JSON
    elif ext == ".html" or ext == ".htm":
        return FileType.HTML
    elif ext in (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff",
                 ".gif", ".webp"):
        return FileType.IMAGE

    return FileType.UNKNOWN


def _detect_zip_type(path: Path) -> FileType:
    """Inspect a ZIP container: docx/xlsx/pptx vs plain zip."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except Exception:
        return FileType.UNKNOWN
    if any(n.startswith("word/") for n in names):
        return FileType.DOCX
    if any(n.startswith("xl/") for n in names):
        return FileType.XLSX
    if any(n.startswith("ppt/") for n in names):
        return FileType.PPTX
    return FileType.UNKNOWN


def _detect_ole2_type(path: Path) -> FileType:
    """Inspect an OLE2 container: doc/xls/ppt/mpp."""
    try:
        with open(path, "rb") as f:
            data = f.read(4096)
    except Exception:
        return FileType.UNKNOWN
    for sig, ftype in OLE2_SIGNATURES:
        if sig in data:
            return ftype
    return FileType.UNKNOWN


def detect_dwg_version(file_path: str | Path) -> tuple[str, str]:
    """Read DWG file header to identify version.
    
    DWG files start with a 6-byte version string like "AC1032".
    
    Args:
        file_path: Path to the DWG file.
        
    Returns:
        Tuple of (version_code, version_name).
        If the file is not a valid DWG, returns ("", "Unknown").
    """
    path = Path(file_path)
    try:
        with open(path, "rb") as f:
            header = f.read(6)
    except Exception:
        return "", "Unknown"

    if len(header) < 6 or header[:2] != b"AC":
        return "", "Unknown"

    version_name = DWG_VERSION_MAP.get(header, f"Unknown ({header.decode('ascii', errors='replace')})")
    return header.decode("ascii", errors="replace"), version_name


def detect_dxf_version(file_path: str | Path) -> tuple[str, str]:
    """Detect DXF file version by reading $ACADVER header variable.
    
    This is a lightweight scan that doesn't load the full file.
    
    Args:
        file_path: Path to the DXF file.
        
    Returns:
        Tuple of (version_code, version_name).
    """
    path = Path(file_path)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            # DXF is text format; scan first ~10000 chars for $ACADVER
            content = f.read(50000)
        
        # Find $ACADVER
        idx = content.find("$ACADVER")
        if idx == -1:
            return "", "Unknown"
        
        # The value is on the line after the group code
        lines = content[idx:].split("\n")
        # $ACADVER is the variable name (group code 9)
        # Next line is group code 1, then the value
        for i, line in enumerate(lines):
            line = line.strip()
            if line == "1" and i + 1 < len(lines):
                version_code = lines[i + 1].strip()
                version_name = DWG_VERSION_MAP.get(
                    version_code.encode("ascii", errors="replace"),
                    f"Unknown ({version_code})",
                )
                return version_code, version_name
    except Exception:
        pass

    return "", "Unknown"


def get_file_info(file_path: str | Path) -> dict:
    """Get comprehensive file information.
    
    Returns dict with: file_name, file_path, file_size, file_type,
    cad_version, cad_version_name, modified_time, created_time.
    """
    path = Path(file_path)
    if not path.exists():
        return {"error": f"File not found: {file_path}"}

    stat = path.stat()
    file_type = detect_file_type(path)
    
    cad_version = ""
    cad_version_name = ""
    
    if file_type == FileType.DWG:
        cad_version, cad_version_name = detect_dwg_version(path)
    elif file_type == FileType.DXF:
        cad_version, cad_version_name = detect_dxf_version(path)

    return {
        "file_name": path.name,
        "file_path": str(path.absolute()),
        "file_size": stat.st_size,
        "file_type": file_type.value,
        "cad_version": cad_version,
        "cad_version_name": cad_version_name,
        "modified_time": stat.st_mtime,
        "created_time": stat.st_ctime,
    }
