"""Geometry utility functions for CAD entities."""

import math
from typing import Any

from src.normalizer.schema import BoundingBox


def compute_bbox_from_points(points: list[tuple[float, ...]]) -> BoundingBox:
    """Compute bounding box from a list of coordinate points.

    Args:
        points: List of (x, y) or (x, y, z) tuples.

    Returns:
        BoundingBox with min/max coordinates.
    """
    if not points:
        return BoundingBox(
            min_x=0, min_y=0, min_z=0,
            max_x=0, max_y=0, max_z=0,
            width=0, height=0,
        )

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] if len(p) > 2 else 0.0 for p in points]

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    min_z, max_z = min(zs), max(zs)

    return BoundingBox(
        min_x=min_x, min_y=min_y, min_z=min_z,
        max_x=max_x, max_y=max_y, max_z=max_z,
        width=max_x - min_x,
        height=max_y - min_y,
    )


def bbox_from_center_radius(
    cx: float, cy: float, cz: float, radius: float
) -> BoundingBox:
    """Compute bounding box for a circle/arc given center and radius."""
    return BoundingBox(
        min_x=cx - radius, min_y=cy - radius, min_z=cz,
        max_x=cx + radius, max_y=cy + radius, max_z=cz,
        width=2 * radius,
        height=2 * radius,
    )


def arc_endpoints(
    cx: float, cy: float, cz: float,
    radius: float, start_angle: float, end_angle: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Compute arc start and end points from center, radius, and angles.

    Angles are in degrees.
    """
    s_rad = math.radians(start_angle)
    e_rad = math.radians(end_angle)
    start = (cx + radius * math.cos(s_rad), cy + radius * math.sin(s_rad), cz)
    end = (cx + radius * math.cos(e_rad), cy + radius * math.sin(e_rad), cz)
    return start, end


def arc_length(radius: float, start_angle: float, end_angle: float) -> float:
    """Compute arc length. Angles in degrees."""
    angle_span = end_angle - start_angle
    if angle_span < 0:
        angle_span += 360
    return radius * math.radians(angle_span)


def line_length(
    p1: tuple[float, ...], p2: tuple[float, ...]
) -> float:
    """Compute distance between two points."""
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(p1, p2)))


def line_angle(
    p1: tuple[float, ...], p2: tuple[float, ...]
) -> float:
    """Compute angle of a line in degrees (0-360)."""
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    return math.degrees(math.atan2(dy, dx)) % 360


def bbox_intersects(a: BoundingBox, b: BoundingBox) -> bool:
    """Check if two bounding boxes intersect."""
    return not (
        a.max_x < b.min_x
        or a.min_x > b.max_x
        or a.max_y < b.min_y
        or a.min_y > b.max_y
    )


def bbox_distance(a: BoundingBox, b: BoundingBox) -> float:
    """Compute minimum distance between two bounding boxes."""
    if bbox_intersects(a, b):
        return 0.0

    dx = max(0, max(b.min_x - a.max_x, a.min_x - b.max_x))
    dy = max(0, max(b.min_y - a.max_y, a.min_y - b.max_y))
    return math.sqrt(dx * dx + dy * dy)


def bbox_contains(outer: BoundingBox, inner: BoundingBox) -> bool:
    """Check if outer bbox fully contains inner bbox."""
    return (
        outer.min_x <= inner.min_x
        and outer.max_x >= inner.max_x
        and outer.min_y <= inner.min_y
        and outer.max_y >= inner.max_y
    )


def bbox_area(box: BoundingBox) -> float:
    """Compute the 2D area of a bounding box (width * height)."""
    w = box.max_x - box.min_x
    h = box.max_y - box.min_y
    if w <= 0 or h <= 0:
        return 0.0
    return w * h
