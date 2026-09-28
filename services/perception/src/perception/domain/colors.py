"""11 named-colour classification from HSV — pure (design_architecture.md
§7.1: "HSV k-means dominant colour on upper/lower halves of person crops;
colour for vehicles/bags"; P2-D3 AC: "11 named colours").

Takes degrees/fractions (H in [0,360), S and V in [0,1]) rather than
OpenCV's H in [0,180)/S,V in [0,255] convention, so this stays decoupled
from OpenCV and independently testable — the adapter that actually runs
k-means on crops converts before calling this.

Bins are approximate and tunable, not a colorimetric standard — the
design goal is "cheap, explainable" (style_guide.md / techstack.md §4),
not perceptual accuracy.
"""

from __future__ import annotations

NAMED_COLORS = (
    "black",
    "white",
    "gray",
    "red",
    "orange",
    "yellow",
    "green",
    "cyan",
    "blue",
    "purple",
    "pink",
)

_BLACK_MAX_V = 0.15
_ACHROMATIC_MAX_S = 0.15
_WHITE_MIN_V = 0.85

# (hue upper bound exclusive, name) — checked in order, hue pre-wrapped to [0, 360)
_HUE_BINS: tuple[tuple[float, str], ...] = (
    (15, "red"),
    (45, "orange"),
    (65, "yellow"),
    (170, "green"),
    (200, "cyan"),
    (255, "blue"),
    (290, "purple"),
    (345, "pink"),
    (360, "red"),  # wraps back to red
)


def classify_color(hue_deg: float, saturation: float, value: float) -> str:
    """Classify one HSV pixel/mean into one of the 11 `NAMED_COLORS`."""
    if not (0 <= saturation <= 1 and 0 <= value <= 1):
        raise ValueError(f"saturation and value must be in [0,1]: s={saturation}, v={value}")
    hue_deg = hue_deg % 360

    if value < _BLACK_MAX_V:
        return "black"
    if saturation < _ACHROMATIC_MAX_S:
        return "white" if value > _WHITE_MIN_V else "gray"

    for upper_bound, name in _HUE_BINS:
        if hue_deg < upper_bound:
            return name
    msg = f"unreachable: hue_deg={hue_deg} not covered by _HUE_BINS"  # pragma: no cover
    raise AssertionError(msg)  # pragma: no cover
