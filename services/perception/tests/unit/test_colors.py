"""Tests for perception.domain.colors — 11-colour HSV classification."""

import pytest
from perception.domain.colors import NAMED_COLORS, classify_color


def test_named_colors_has_exactly_eleven() -> None:
    assert len(NAMED_COLORS) == 11


@pytest.mark.parametrize(
    ("hue", "sat", "val", "expected"),
    [
        (0, 0.9, 0.05, "black"),  # very dark, regardless of hue
        (0, 0.05, 0.95, "white"),  # low saturation, bright
        (0, 0.05, 0.5, "gray"),  # low saturation, mid brightness
        (0, 0.8, 0.8, "red"),
        (30, 0.8, 0.8, "orange"),
        (55, 0.8, 0.8, "yellow"),
        (120, 0.8, 0.8, "green"),
        (185, 0.8, 0.8, "cyan"),
        (230, 0.8, 0.8, "blue"),
        (270, 0.8, 0.8, "purple"),
        (320, 0.8, 0.8, "pink"),
        (355, 0.8, 0.8, "red"),  # wraps back to red near 360
    ],
)
def test_classify_color(hue: float, sat: float, val: float, expected: str) -> None:
    assert classify_color(hue, sat, val) == expected


def test_classify_color_wraps_hue_over_360() -> None:
    assert classify_color(360 + 5, 0.8, 0.8) == classify_color(5, 0.8, 0.8)


@pytest.mark.parametrize(("bad_s", "bad_v"), [(-0.1, 0.5), (1.1, 0.5), (0.5, -0.1), (0.5, 1.1)])
def test_classify_color_rejects_out_of_range_s_or_v(bad_s: float, bad_v: float) -> None:
    with pytest.raises(ValueError, match=r"saturation and value must be in \[0,1\]"):
        classify_color(0, bad_s, bad_v)


def test_classify_color_result_is_always_a_named_color() -> None:
    for hue in range(0, 360, 7):
        assert classify_color(hue, 0.8, 0.8) in NAMED_COLORS
