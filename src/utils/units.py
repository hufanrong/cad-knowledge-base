"""Unit detection and conversion for CAD files."""

# AutoCAD INSUNITS values and their meanings
INSUNITS_MAP = {
    0: ("Unitless", None),
    1: ("Inch", "inch"),
    2: ("Foot", "feet"),
    3: ("Mile", "mile"),
    4: ("Millimeter", "mm"),
    5: ("Centimeter", "cm"),
    6: ("Meter", "m"),
    7: ("Kilometer", "km"),
    8: ("Microinch", "microinch"),
    9: ("Mil", "mil"),
    10: ("Yard", "yard"),
    11: ("Angstrom", "angstrom"),
    12: ("Nanometer", "nm"),
    13: ("Micron", "micron"),
    14: ("Decimeter", "dm"),
    15: ("Decameter", "dam"),
    16: ("Hectometer", "hm"),
    17: ("Gigameter", "Gm"),
    18: ("Astronomical Unit", "AU"),
    19: ("Light Year", "ly"),
    20: ("Parsec", "pc"),
}

# Conversion factors to mm
TO_MM = {
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "km": 1_000_000.0,
    "inch": 25.4,
    "feet": 304.8,
    "yard": 914.4,
    "mile": 1_609_344.0,
    "dm": 100.0,
    "mil": 0.0254,
    "microinch": 0.0000254,
}


def detect_units(header_vars: dict) -> tuple[str, int | None]:
    """Detect drawing units from DXF/DWG header variables.

    Args:
        header_vars: Dict of header variable names to values.

    Returns:
        Tuple of (unit_name, insunits_raw_value).
    """
    insunits = header_vars.get("$INSUNITS", 0)
    if insunits in INSUNITS_MAP:
        name, normalized = INSUNITS_MAP[insunits]
        return normalized or name.lower(), insunits
    return "unknown", insunits


def convert_to_mm(value: float, from_unit: str) -> float:
    """Convert a value from the given unit to millimeters."""
    if from_unit is None or from_unit == "unknown":
        return value  # Can't convert, return as-is
    factor = TO_MM.get(from_unit.lower())
    if factor is None:
        return value  # Unknown unit, return as-is
    return value * factor


def format_coordinate(x: float, y: float, z: float = 0) -> str:
    """Format coordinates for human-readable output."""
    return f"X={x:.2f} Y={y:.2f} Z={z:.2f}"
