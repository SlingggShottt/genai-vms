"""`running` — a person moving faster than `speed` for at least `min_samples`
samples (design_architecture.md §7.3; defaults S = 0.35 /s, k = 3, severity low).

Camera-wide: it needs no zones. The speed is the twin's per-object
`motion.speed` — the normalized bbox-centre displacement per second that
perception computes from the track — so it is measured in image fractions per
second: 0.35 means crossing about a third of the frame width every second.
For scale, on the demo footage (a busy pedestrian street) walking people measured
a median of 0.009 and a 99th percentile of 0.083.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import Field
from vms_common.contracts.twin import FrameObject

from events.domain.rules.base import CameraRule, FrameContext, Hit, RuleParams, Severity, rule


class RunningParams(RuleParams):
    # A runner is in view for a few seconds, so the window that joins their samples
    # into one candidate is tighter than the 5 s default of the zone rules.
    debounce_s: float = Field(
        default=2.0,
        ge=0,
        description="Longest gap (s) between two fast samples of the same person.",
    )
    speed: float = Field(
        default=0.35, gt=0, description="Faster than this (normalized frame units per second)."
    )
    min_samples: int = Field(
        default=3, ge=1, description="Fast samples needed before it becomes a candidate."
    )
    categories: list[str] = Field(default_factory=lambda: ["person"])

    def required_frames(self) -> int:
        return self.min_samples


@rule("running")
class Running(CameraRule):
    event_type = "running"
    default_severity: Severity = "low"
    Params = RunningParams

    def evaluate_camera(
        self,
        objects: Sequence[FrameObject],
        params: RuleParams,
        ctx: FrameContext,
        memory: dict[str, Any],
    ) -> list[Hit]:
        assert isinstance(params, RunningParams)  # noqa: S101 - type narrowing only
        hits: list[Hit] = []
        for obj in objects:
            if obj.category not in params.categories or obj.motion is None:
                continue
            speed = obj.motion.speed
            if speed > params.speed:
                hits.append(
                    Hit(
                        key=obj.track_id,
                        track_ids=(obj.track_id,),
                        # Heuristic, uncalibrated: just over the limit ~0.5, double it 1.0.
                        score=min(1.0, speed / (2 * params.speed)),
                        metrics={"speed": speed},
                    )
                )
        return hits
