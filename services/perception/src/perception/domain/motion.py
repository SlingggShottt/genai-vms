"""Speed and direction from centroid displacement — pure
(design_architecture.md §7.1: "speed and direction from track centroid
displacement (normalized units/s)").

Centroids are normalized `[0,1]` bbox-center coordinates, so `speed` comes
out directly in "normalized units/s" (twin.v1's `ObjectMotion.speed`).
`direction_deg` follows image coordinates (y grows downward): 0° = moving
right (+x), 90° = moving down (+y), matching `atan2(dy, dx)`.
"""

from __future__ import annotations

import math


def compute_motion(
    prev_centroid: tuple[float, float], curr_centroid: tuple[float, float], dt_s: float
) -> tuple[float, float]:
    """Return `(speed, direction_deg)` between two centroids `dt_s` apart."""
    if dt_s <= 0:
        raise ValueError(f"dt_s must be > 0, got {dt_s}")

    dx = curr_centroid[0] - prev_centroid[0]
    dy = curr_centroid[1] - prev_centroid[1]
    distance = math.hypot(dx, dy)

    speed = distance / dt_s
    direction_deg = math.degrees(math.atan2(dy, dx)) % 360
    return speed, direction_deg


def bbox_center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def bbox_bottom_center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    """Used for zone membership (design_architecture.md §7.1: bottom-centre
    point-in-polygon), not motion — kept here alongside `bbox_center` since
    both are bbox-to-point reductions."""
    x1, _y1, x2, y2 = bbox
    return ((x1 + x2) / 2, y2)
