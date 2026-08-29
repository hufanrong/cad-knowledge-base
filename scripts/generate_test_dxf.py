"""Generate test DXF files for unit testing.

This script creates DXF files containing all supported entity types,
block attributes, dimensions, Chinese text, and multiple layouts.
"""

import math
from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment


def generate_test_dxf(output_path: str | Path, version: str = "R2018"):
    """Generate a comprehensive test DXF file.
    
    Args:
        output_path: Path to save the DXF file.
        version: DXF version string (R12, R2000, R2010, R2018, etc.)
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.new(version)
    msp = doc.modelspace()

    # Set units to millimeters
    doc.header["$INSUNITS"] = 4  # 4 = Millimeter

    # ─── Layers ──────────────────────────────────────────────
    doc.layers.add(name="EQUIPMENT", color=1)
    doc.layers.add(name="PIPE", color=3)
    doc.layers.add(name="标注", color=2)
    doc.layers.add(name="标题栏", color=7)
    doc.layers.add(name="TECHNICAL", color=5)

    # ─── LINE ────────────────────────────────────────────────
    msp.add_line((0, 0), (1000, 0), dxfattribs={"layer": "EQUIPMENT"})
    msp.add_line((0, 0), (0, 500), dxfattribs={"layer": "EQUIPMENT"})
    msp.add_line((1000, 0), (1000, 500), dxfattribs={"layer": "EQUIPMENT"})
    msp.add_line((0, 500), (1000, 500), dxfattribs={"layer": "EQUIPMENT"})

    # ─── CIRCLE ──────────────────────────────────────────────
    msp.add_circle((500, 250), 100, dxfattribs={"layer": "EQUIPMENT"})
    msp.add_circle((200, 250), 50, dxfattribs={"layer": "PIPE"})

    # ─── ARC ─────────────────────────────────────────────────
    msp.add_arc((500, 250), 150, 0, 180, dxfattribs={"layer": "EQUIPMENT"})

    # ─── LWPOLYLINE ──────────────────────────────────────────
    msp.add_lwpolyline(
        [(1100, 0), (1500, 0), (1500, 300), (1100, 300), (1100, 0)],
        close=True,
        dxfattribs={"layer": "EQUIPMENT"},
    )

    # ─── POLYLINE (2D) ───────────────────────────────────────
    pline = msp.add_polyline2d(
        [(0, 600), (200, 600), (200, 800), (0, 800)],
        close=True,
        dxfattribs={"layer": "EQUIPMENT"},
    )

    # ─── SPLINE ──────────────────────────────────────────────
    fit_points = [(0, 900), (250, 1000), (500, 900), (750, 1000), (1000, 900)]
    msp.add_spline(fit_points, dxfattribs={"layer": "EQUIPMENT"})

    # ─── ELLIPSE ─────────────────────────────────────────────
    msp.add_ellipse((500, 1200), (200, 0), ratio=0.5, dxfattribs={"layer": "EQUIPMENT"})

    # ─── TEXT ────────────────────────────────────────────────
    msp.add_text(
        "酸化窑 φ4500×45000",
        height=20,
        dxfattribs={"layer": "标注", "insert": (0, 1300)},
    )
    msp.add_text(
        "MILL-001",
        height=15,
        dxfattribs={"layer": "标注", "insert": (300, 1300)},
    )
    msp.add_text(
        "EL+5.200",
        height=10,
        dxfattribs={"layer": "标注", "insert": (600, 1300)},
    )

    # ─── MTEXT ───────────────────────────────────────────────
    mtext = msp.add_mtext(
        "技术要求：\n1. 焊缝按GB/T 985执行\n2. 设备重量：未识别\n3. 设计压力：0.5MPa",
        dxfattribs={"layer": "TECHNICAL", "insert": (0, 1500)},
    )
    mtext.char_height = 10

    # MTEXT with formatting codes
    mtext2 = msp.add_mtext(
        r"{\C2;设备名称：}{球磨机}\P{\C3;型号：}{MQG-3245}\P{\C5;功率：}{未识别}",
        dxfattribs={"layer": "TECHNICAL", "insert": (500, 1500)},
    )
    mtext2.char_height = 10

    # ─── DIMENSION (Linear) ──────────────────────────────────
    dim1 = msp.add_linear_dim(
        base=(0, -50),
        p1=(0, 0),
        p2=(1000, 0),
        angle=0,
        dxfattribs={"layer": "标注"},
    )
    dim1.render()

    # ─── DIMENSION (Aligned) ─────────────────────────────────
    dim2 = msp.add_aligned_dim(
        p1=(0, 0),
        p2=(0, 500),
        distance=50,
        dxfattribs={"layer": "标注"},
    )
    dim2.render()

    # ─── DIMENSION (Radius) ──────────────────────────────────
    dim3 = msp.add_radius_dim(
        center=(500, 250),
        radius=100,
        angle=45,
        dxfattribs={"layer": "标注"},
    )
    dim3.render()

    # ─── DIMENSION (Diameter) ────────────────────────────────
    dim4 = msp.add_diameter_dim(
        center=(200, 250),
        radius=50,
        angle=135,
        dxfattribs={"layer": "标注"},
    )
    dim4.render()

    # ─── HATCH ───────────────────────────────────────────────
    hatch = msp.add_hatch(color=2, dxfattribs={"layer": "标注"})
    hatch.paths.add_polyline_path(
        [(1100, 0), (1500, 0), (1500, 300), (1100, 300), (1100, 0)],
        is_closed=True,
    )

    # ─── POINT ───────────────────────────────────────────────
    msp.add_point((500, 250), dxfattribs={"layer": "EQUIPMENT"})

    # ─── BLOCK with ATTRIB ───────────────────────────────────
    # Define a block with attribute definitions
    block_def = doc.blocks.new(name="EQUIP_TAG")
    block_def.add_line((0, 0), (100, 0))
    block_def.add_line((0, 0), (0, 30))
    block_def.add_line((100, 0), (100, 30))
    block_def.add_line((0, 30), (100, 30))
    block_def.add_attdef(
        tag="EQUIP_NO",
        insert=(10, 10),
        height=8,
        dxfattribs={"layer": "标题栏"},
    )
    block_def.add_attdef(
        tag="EQUIP_NAME",
        insert=(10, 20),
        height=8,
        dxfattribs={"layer": "标题栏"},
    )

    # Insert the block with attributes
    insert = msp.add_blockref(
        name="EQUIP_TAG",
        insert=(200, 1000),
        dxfattribs={"layer": "EQUIPMENT"},
    )
    insert.add_auto_attribs({
        "EQUIP_NO": "MILL-001",
        "EQUIP_NAME": "球磨机",
    })

    # Another insert
    insert2 = msp.add_blockref(
        name="EQUIP_TAG",
        insert=(400, 1000),
        dxfattribs={"layer": "EQUIPMENT"},
    )
    insert2.add_auto_attribs({
        "EQUIP_NO": "MILL-002",
        "EQUIP_NAME": "酸化窑",
    })

    # ─── Paper Space Layout ──────────────────────────────────
    layout = doc.layouts.get("Layout1")
    layout.add_text(
        "图纸标题: 酸化窑总图",
        height=5,
        dxfattribs={"insert": (0, 0), "layer": "标题栏"},
    )
    layout.add_line((0, 0), (200, 0), dxfattribs={"layer": "标题栏"})

    # ─── Title Block inside the frame (Model space, lower-right) ──
    # The frame is (0,0)-(1000,500). Title block is the lower-right
    # area (x: 600-1000, y: 0-200).
    tb = [
        ("图号", "2024-001"),
        ("图纸名称", "酸化窑总图"),
        ("比例", "1:100"),
        ("设计", "ZHANG"),
        ("审核", "未识别"),
        ("日期", "2026-08-17"),
    ]
    for i, (key, value) in enumerate(tb):
        y = 50 + i * 25
        msp.add_text(
            key,
            height=8,
            dxfattribs={"layer": "标题栏", "insert": (610, y)},
        )
        msp.add_text(
            value,
            height=8,
            dxfattribs={"layer": "标题栏", "insert": (680, y)},
        )

    # ─── Save ────────────────────────────────────────────────
    doc.saveas(str(path))
    return path


def generate_simple_dxf(output_path: str | Path, version: str = "R2018"):
    """Generate a simple DXF file with basic entities."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.new(version)
    msp = doc.modelspace()
    doc.header["$INSUNITS"] = 4

    doc.layers.add(name="TestLayer", color=1)

    msp.add_line((0, 0), (100, 0), dxfattribs={"layer": "TestLayer"})
    msp.add_circle((50, 50), 25, dxfattribs={"layer": "TestLayer"})
    msp.add_text("Hello CAD", height=5, dxfattribs={"layer": "TestLayer", "insert": (0, 100)})

    doc.saveas(str(path))
    return path


if __name__ == "__main__":
    import sys

    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else "tests/fixtures/dxf"

    # Generate comprehensive test file
    f1 = generate_test_dxf(output_dir / "test_all_entities.dxf", "R2018")
    print(f"Generated: {f1}")

    # Generate simple test file
    f2 = generate_simple_dxf(output_dir / "test_simple.dxf", "R2018")
    print(f"Generated: {f2}")

    # Generate R12 version
    try:
        f3 = generate_simple_dxf(output_dir / "test_r12.dxf", "R12")
        print(f"Generated: {f3}")
    except Exception as e:
        print(f"R12 generation failed: {e}")

    # Generate R2000 version
    f4 = generate_simple_dxf(output_dir / "test_r2000.dxf", "R2000")
    print(f"Generated: {f4}")

    # Phase 8: generate all remaining versions supported by ezdxf.
    # NOTE: ezdxf does NOT support R13 (AC1012) / R14 (AC1014) — skipped.
    extra_versions = [
        ("test_r2004.dxf", "R2004"),
        ("test_r2007.dxf", "R2007"),
        ("test_r2010.dxf", "R2010"),
        ("test_r2013.dxf", "R2013"),
    ]
    for fname, ver in extra_versions:
        try:
            f = generate_simple_dxf(output_dir / fname, ver)
            print(f"Generated: {f}")
        except Exception as e:
            print(f"{ver} generation failed: {e}")

    print(f"\nAll test DXF files generated in: {output_dir}")
