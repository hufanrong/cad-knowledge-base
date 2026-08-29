"""Generate DWG test fixtures from existing DXF test files.

Uses ODA File Converter (DXF -> DWG) to produce DWG fixtures covering
multiple AutoCAD versions, so DWG parsing can be tested end-to-end.

Run:  python scripts/generate_test_dwg.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.parsers.oda_converter import ODAConverter, is_oda_available  # noqa: E402

# (dxf fixture name, ODA output version, resulting DWG header version)
# NOTE: R13/R14 skipped because ezdxf cannot produce those DXF versions.
CONVERSIONS = [
    ("test_all_entities.dxf", "ACAD2018", "AC1032"),
    ("test_simple.dxf", "ACAD2018", "AC1032"),
    ("test_r12.dxf", "ACAD12", "AC1009"),
    ("test_r2000.dxf", "ACAD2000", "AC1015"),
    ("test_r2004.dxf", "ACAD2004", "AC1018"),
    ("test_r2007.dxf", "ACAD2007", "AC1021"),
    ("test_r2010.dxf", "ACAD2010", "AC1024"),
    ("test_r2013.dxf", "ACAD2013", "AC1027"),
]


def main() -> int:
    if not is_oda_available():
        print("ERROR: ODA File Converter 未安装，无法生成 DWG 测试文件")
        return 1

    project_root = Path(__file__).resolve().parent.parent
    dxf_dir = project_root / "tests" / "fixtures" / "dxf"
    dwg_dir = project_root / "tests" / "fixtures" / "dwg"
    dwg_dir.mkdir(parents=True, exist_ok=True)

    converter = ODAConverter()
    success = 0

    for dxf_name, oda_version, expected_header in CONVERSIONS:
        src = dxf_dir / dxf_name
        if not src.exists():
            print(f"SKIP: 源 DXF 不存在 {dxf_name}")
            continue

        # ODA works on folders; copy the DXF to a temp input dir
        with tempfile.TemporaryDirectory(prefix="cadkb_gen_") as tmp_in:
            input_dir = Path(tmp_in)
            shutil_copy(src, input_dir)
            # Use the converter's directory mode to produce DWG output
            count = converter.convert_directory(
                input_dir=input_dir,
                output_dir=dwg_dir,
                output_version=oda_version,
                output_format="DWG",
                recurse=False,
                audit=True,
            )

        # Check expected output (same stem, .dwg)
        out = dwg_dir / (Path(dxf_name).stem + ".dwg")
        if out.exists() and out.stat().st_size > 0:
            # Verify DWG header version
            with open(out, "rb") as f:
                header = f.read(6).decode("ascii", errors="replace")
            ok = header == expected_header
            print(f"{'OK' if ok else 'VERIFY-FAIL'}: {dxf_name} -> {out.name} (header={header}, expected={expected_header}, size={out.stat().st_size})")
            if ok:
                success += 1
        else:
            print(f"FAIL: 未生成 {dxf_name} 对应的 DWG (converted={count})")

    print(f"\n完成: {success}/{len(CONVERSIONS)} 个 DWG 测试文件生成成功")
    return 0 if success == len(CONVERSIONS) else 1


def shutil_copy(src: Path, dest_dir: Path) -> None:
    import shutil

    shutil.copy2(src, dest_dir / src.name)


if __name__ == "__main__":
    raise SystemExit(main())
