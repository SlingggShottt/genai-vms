"""Tests for perception.domain.motion."""

import math

import pytest
from perception.domain.motion import bbox_bottom_center, bbox_center, compute_motion


def test_compute_motion_moving_right() -> None:
    speed, direction = compute_motion((0.1, 0.5), (0.3, 0.5), dt_s=1.0)

    assert speed == pytest.approx(0.2)
    assert direction == pytest.approx(0.0)


def test_compute_motion_moving_down() -> None:
    speed, direction = compute_motion((0.5, 0.1), (0.5, 0.3), dt_s=1.0)

    assert speed == pytest.approx(0.2)
    assert direction == pytest.approx(90.0)


def test_compute_motion_moving_left() -> None:
    _speed, direction = compute_motion((0.5, 0.5), (0.3, 0.5), dt_s=1.0)

    assert direction == pytest.approx(180.0)


def test_compute_motion_moving_up() -> None:
    _speed, direction = compute_motion((0.5, 0.5), (0.5, 0.3), dt_s=1.0)

    assert direction == pytest.approx(270.0)


def test_compute_motion_scales_with_dt() -> None:
    speed_1s, _ = compute_motion((0.0, 0.0), (0.1, 0.0), dt_s=1.0)
    speed_2s, _ = compute_motion((0.0, 0.0), (0.1, 0.0), dt_s=2.0)

    assert speed_2s == pytest.approx(speed_1s / 2)


def test_compute_motion_rejects_non_positive_dt() -> None:
    with pytest.raises(ValueError, match="dt_s must be > 0"):
        compute_motion((0, 0), (1, 1), dt_s=0)


def test_compute_motion_stationary_has_zero_speed() -> None:
    speed, _ = compute_motion((0.5, 0.5), (0.5, 0.5), dt_s=1.0)
    assert speed == 0.0


def test_bbox_center() -> None:
    assert bbox_center((0.2, 0.3, 0.6, 0.7)) == pytest.approx((0.4, 0.5))


def test_bbox_bottom_center() -> None:
    assert bbox_bottom_center((0.2, 0.3, 0.6, 0.7)) == pytest.approx((0.4, 0.7))


def test_direction_is_always_in_0_360() -> None:
    for dx, dy in [(1, 1), (-1, 1), (-1, -1), (1, -1)]:
        _speed, direction = compute_motion((0.5, 0.5), (0.5 + dx, 0.5 + dy), dt_s=1.0)
        assert 0 <= direction < 360
        assert not math.isnan(direction)
