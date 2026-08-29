"""CAD file parsers.

- DXFParser: reads DXF via ezdxf
- DWGParser: reads DWG via ODA File Converter -> DXF -> ezdxf
- ODAConverter: command-line wrapper around ODAFileConverter.exe
"""

from src.parsers.base_parser import BaseParser
from src.parsers.dxf_parser import DXFParser
from src.parsers.dwg_parser import DWGParser
from src.parsers.oda_converter import ODAConverter, is_oda_available

__all__ = [
    "BaseParser",
    "DXFParser",
    "DWGParser",
    "ODAConverter",
    "is_oda_available",
]
