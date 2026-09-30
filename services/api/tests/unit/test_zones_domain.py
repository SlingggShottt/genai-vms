"""P2-J4: pure polygon validation — no DB."""

from __future__ import annotations

import pytest
from api.domain.zones import validate_polygon


def test_accepts_a_valid_triangle() -> None:
    points = [(0.1, 0.1), (0.5, 0.2), (0.3, 0.6)]
    assert validate_polygon(points) == points


def test_rejects_fewer_than_three_points() -> None:
    with pytest.raises(ValueError, match="between 3 and 32"):
        validate_polygon([(0.1, 0.1), (0.5, 0.2)])


def test_rejects_more_than_32_points() -> None:
    points = [(0.01 * i, 0.01 * i) for i in range(33)]
    with pytest.raises(ValueError, match="between 3 and 32"):
        validate_polygon(points)


def test_accepts_exactly_32_points() -> None:
    points = [(0.01 * i, 0.01 * i) for i in range(32)]
    assert validate_polygon(points) == points


@pytest.mark.parametrize("point", [(-0.1, 0.5), (1.1, 0.5), (0.5, -0.1), (0.5, 1.1)])
def test_rejects_a_point_outside_zero_one(point: tuple[float, float]) -> None:
    with pytest.raises(ValueError, match="normalized"):
        validate_polygon([(0.1, 0.1), (0.5, 0.2), point])


def test_accepts_boundary_values_zero_and_one() -> None:
    points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    assert validate_polygon(points) == points
