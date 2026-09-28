"""Zone membership via bottom-centre point-in-polygon — pure
(design_architecture.md §7.1, FR-PER-04).
"""

from __future__ import annotations

from vms_common.contracts.zones import ZoneInternal

from perception.domain.motion import bbox_bottom_center


def point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test. `polygon`: `[(x, y), ...]`, normalized."""
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def zones_for_bbox(
    bbox: tuple[float, float, float, float], camera_id: str, zones: list[ZoneInternal]
) -> list[str]:
    """Zone names (twin.v1's `FrameObject.zones` convention) containing this
    bbox's bottom-centre point, restricted to `camera_id`'s zones."""
    point = bbox_bottom_center(bbox)
    return [
        zone.name
        for zone in zones
        if zone.camera_id == camera_id and point_in_polygon(point, zone.polygon)
    ]
