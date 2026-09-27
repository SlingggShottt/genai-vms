"""Tests for perception.domain.zones."""

from perception.domain.zones import point_in_polygon, zones_for_bbox
from vms_common.contracts.zones import ZoneInternal

SQUARE = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]


def test_point_in_polygon_inside() -> None:
    assert point_in_polygon((0.5, 0.5), SQUARE) is True


def test_point_in_polygon_outside() -> None:
    assert point_in_polygon((0.1, 0.1), SQUARE) is False


def test_point_in_polygon_just_outside_edge() -> None:
    assert point_in_polygon((0.9, 0.5), SQUARE) is False


def test_zones_for_bbox_empty_when_bottom_centre_outside() -> None:
    zones = [
        ZoneInternal(
            id="z1", camera_id="cam01", name="entrance", zone_type="entrance", polygon=SQUARE
        )
    ]

    result = zones_for_bbox((0.4, 0.6, 0.6, 0.9), "cam01", zones)  # bottom-centre = (0.5, 0.9)

    assert result == []  # bottom-centre (0.5, 0.9) is outside SQUARE (y up to 0.8)


def test_zones_for_bbox_uses_bottom_centre_not_bbox_centre() -> None:
    zones = [
        ZoneInternal(
            id="z1", camera_id="cam01", name="entrance", zone_type="entrance", polygon=SQUARE
        )
    ]
    # bbox centre (0.5, 0.5) is inside SQUARE, and so is bottom-centre (0.5, 0.7)
    result = zones_for_bbox((0.3, 0.3, 0.7, 0.7), "cam01", zones)

    assert result == ["entrance"]


def test_zones_for_bbox_filters_by_camera() -> None:
    zones = [
        ZoneInternal(
            id="z1", camera_id="cam02", name="entrance", zone_type="entrance", polygon=SQUARE
        )
    ]

    result = zones_for_bbox((0.4, 0.4, 0.6, 0.6), "cam01", zones)  # wrong camera

    assert result == []


def test_zones_for_bbox_can_match_multiple_overlapping_zones() -> None:
    zones = [
        ZoneInternal(
            id="z1", camera_id="cam01", name="zone-a", zone_type="generic", polygon=SQUARE
        ),
        ZoneInternal(
            id="z2",
            camera_id="cam01",
            name="zone-b",
            zone_type="restricted",
            polygon=[(0.3, 0.3), (0.9, 0.3), (0.9, 0.9), (0.3, 0.9)],
        ),
    ]

    result = zones_for_bbox((0.3, 0.3, 0.7, 0.7), "cam01", zones)

    assert set(result) == {"zone-a", "zone-b"}
