"""Dominant-colour extraction from person/vehicle crops via HSV k-means
(design_architecture.md §7.1: "HSV k-means dominant colour on upper/lower
halves of person crops; colour for vehicles/bags", techstack.md §4: "Cheap,
explainable"). Classification itself is `perception.domain.colors` (pure);
this module is the OpenCV-dependent adapter around it.
"""

from __future__ import annotations

import cv2
import numpy as np

from perception.domain.colors import classify_color

K_MEANS_CLUSTERS = 3
K_MEANS_ATTEMPTS = 3
_KMEANS_CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)


def _dominant_color_name(bgr_crop: np.ndarray) -> str | None:
    """K-means on a BGR crop's pixels in HSV space; returns the largest
    cluster's classified colour name, or `None` for an empty/too-small crop.
    """
    if bgr_crop.size == 0:
        return None
    hsv = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2HSV)
    pixels = hsv.reshape(-1, 3).astype(np.float32)
    if len(pixels) < K_MEANS_CLUSTERS:
        return None

    _compactness, labels, centers = cv2.kmeans(
        pixels,
        K_MEANS_CLUSTERS,
        None,
        _KMEANS_CRITERIA,
        K_MEANS_ATTEMPTS,
        cv2.KMEANS_PP_CENTERS,
    )
    counts = np.bincount(labels.flatten())
    dominant_center = centers[np.argmax(counts)]
    hue_cv, sat_cv, val_cv = dominant_center  # OpenCV: H in [0,180), S,V in [0,255]
    return classify_color(
        hue_deg=float(hue_cv) * 2.0, saturation=float(sat_cv) / 255.0, value=float(val_cv) / 255.0
    )


def person_colors(bgr_crop: np.ndarray) -> tuple[str | None, str | None]:
    """Upper/lower dominant colour for a person crop (top half / bottom half)."""
    if bgr_crop.size == 0:
        return None, None
    height = bgr_crop.shape[0]
    upper = bgr_crop[: height // 2, :, :]
    lower = bgr_crop[height // 2 :, :, :]
    return _dominant_color_name(upper), _dominant_color_name(lower)


def object_color(bgr_crop: np.ndarray) -> str | None:
    """Single dominant colour for non-person categories (vehicles/bags)."""
    return _dominant_color_name(bgr_crop)
