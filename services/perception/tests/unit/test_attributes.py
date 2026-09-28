"""Tests for perception.adapters.attributes — HSV k-means on synthetic
solid-colour crops (needs opencv+numpy; not pure domain logic, hence
adapters/ not domain/, but still fully unit-testable without a GPU)."""

import numpy as np
import pytest
from perception.adapters.attributes import object_color, person_colors

RED_BGR = (36, 28, 237)  # OpenCV is BGR
BLUE_BGR = (222, 128, 33)


def _solid_crop(bgr: tuple[int, int, int], *, h: int = 40, w: int = 20) -> np.ndarray:
    crop = np.zeros((h, w, 3), dtype=np.uint8)
    crop[:, :] = bgr
    return crop


def test_object_color_on_solid_red_crop() -> None:
    assert object_color(_solid_crop(RED_BGR)) == "red"


def test_object_color_on_solid_blue_crop() -> None:
    assert object_color(_solid_crop(BLUE_BGR)) == "blue"


def test_object_color_on_empty_crop_returns_none() -> None:
    assert object_color(np.zeros((0, 0, 3), dtype=np.uint8)) is None


def test_person_colors_splits_upper_and_lower() -> None:
    crop = np.zeros((40, 20, 3), dtype=np.uint8)
    crop[:20, :] = RED_BGR
    crop[20:, :] = BLUE_BGR

    upper, lower = person_colors(crop)

    assert upper == "red"
    assert lower == "blue"


def test_person_colors_on_empty_crop_returns_none_none() -> None:
    assert person_colors(np.zeros((0, 0, 3), dtype=np.uint8)) == (None, None)


@pytest.mark.parametrize("bgr", [RED_BGR, BLUE_BGR, (0, 0, 0), (255, 255, 255), (128, 128, 128)])
def test_object_color_is_deterministic(bgr: tuple[int, int, int]) -> None:
    crop = _solid_crop(bgr)
    assert object_color(crop) == object_color(crop)
