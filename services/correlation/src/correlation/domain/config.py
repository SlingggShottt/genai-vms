"""`config/correlation.yaml` — the knobs of design_architecture.md §7.5, validated.

Loaded once at startup; a typo (unknown key, a weight outside 0..1, a compatibility pair
given two different weights) stops the service with the reason instead of silently changing
what gets linked.

    score = fit_weight * temporal_fit + compat_weight * compatibility(type_a, type_b)

and two events are linked when the camera graph allows it (see `scoring`) and
`score >= link_threshold`. A pair of event types that is not in `compatibility` has weight 0
and is *incompatible*: it never links, whatever the timing.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CorrelationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    link_threshold: float = Field(default=0.5, ge=0, le=1)
    fit_weight: float = Field(default=0.7, ge=0, le=1)
    compat_weight: float = Field(default=0.3, ge=0, le=1)
    # A group closes this long after its last event ended AND no neighbouring camera can
    # still produce a linkable event (the longest transit window of its cameras).
    grace_s: float = Field(default=30.0, ge=0)
    # An open group is re-published at most this often; closing and merging publish at once.
    publish_throttle_s: float = Field(default=5.0, ge=0)
    # Safety valve: a link that would grow a group past this many events is not made, so one
    # busy scene cannot chain the whole site into a single group.
    max_group_events: int = Field(default=50, ge=1)
    compatibility: dict[str, dict[str, float]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if abs(self.fit_weight + self.compat_weight - 1.0) > 1e-9:
            raise ValueError("fit_weight and compat_weight must add up to 1")
        seen: dict[frozenset[str], float] = {}
        for a, row in self.compatibility.items():
            for b, weight in row.items():
                if not 0 <= weight <= 1:
                    raise ValueError(f"compatibility[{a}][{b}] must be between 0 and 1")
                key = frozenset((a, b))
                if key in seen and seen[key] != weight:
                    raise ValueError(
                        f"compatibility of {a!r} and {b!r} is given twice with different weights"
                    )
                seen[key] = weight
        return self

    def compat(self, type_a: str, type_b: str) -> float:
        """Symmetric compatibility weight; 0 when the pair is not listed."""
        weight = self.compatibility.get(type_a, {}).get(type_b)
        if weight is None:
            weight = self.compatibility.get(type_b, {}).get(type_a)
        return weight if weight is not None else 0.0
