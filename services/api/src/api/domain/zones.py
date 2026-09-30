"""Zone polygon validation — no I/O (P2-J4 AC: "normalized polygon
validation (3-32 points, within [0,1])"). Mirrors
`vms_common.contracts.zones.ZoneInternal`'s own check — duplicated, not
imported, since this is a request-schema concern (`api/schemas.py`), not a
cross-service contract (style_guide.md §A.4).
"""

from __future__ import annotations

MIN_POLYGON_POINTS = 3
MAX_POLYGON_POINTS = 32


def validate_polygon(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not (MIN_POLYGON_POINTS <= len(points) <= MAX_POLYGON_POINTS):
        raise ValueError(
            f"polygon must have between {MIN_POLYGON_POINTS} and {MAX_POLYGON_POINTS} points, "
            f"got {len(points)}"
        )
    for x, y in points:
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError(f"polygon points must be normalized to [0,1]: ({x}, {y})")
    return points
