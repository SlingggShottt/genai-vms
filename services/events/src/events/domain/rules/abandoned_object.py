"""`abandoned_object` — a bag or suitcase that has stayed put for `static_s`
while nobody has been near it for `unattended_s` (design_architecture.md §7.3:
"static (Δcentroid < ε) > T and no person within radius r for > T2"; defaults
T = 30 s, r = 0.08, T2 = 20 s, severity high).

Camera-wide (no zones needed). For every bag-like object the rule remembers, in
its `memory` (saved with the camera's state, so it survives restarts):

* an **anchor** — where the object first came to rest — and when (`static_since`).
  The object counts as static while it stays within `static_epsilon` of the
  anchor; moving further resets both, so a bag being carried never accumulates;
* when it last had **no person within `owner_radius`** (`unattended_since`),
  cleared the moment anyone comes near.

It reports a hit once both durations have been met, and tells the engine the
candidate began when the object became unattended (`Hit.since`) — i.e. when the
owner walked away, the moment worth showing in a clip — not when the thresholds
finally elapsed. Anyone (any `owner_categories` object) within the radius counts
as attending it; the rule cannot tell whose bag it is.

Distances are in normalized frame coordinates, so the x and y axes are not the
same length in pixels (the frame is wider than it is tall).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import Field
from vms_common.contracts.twin import FrameObject

from events.domain.rules.base import CameraRule, FrameContext, Hit, RuleParams, Severity, rule


class AbandonedObjectParams(RuleParams):
    static_s: float = Field(
        default=30.0, gt=0, description="T: how long the object must have stayed put."
    )
    unattended_s: float = Field(
        default=20.0, gt=0, description="T2: how long no person may have been near it."
    )
    owner_radius: float = Field(
        default=0.08, gt=0, description="r: a person closer than this (normalized) attends it."
    )
    static_epsilon: float = Field(
        default=0.03,
        gt=0,
        description="ε: it still counts as static within this distance of where it came to rest.",
    )
    categories: list[str] = Field(default_factory=lambda: ["backpack", "handbag", "suitcase"])
    owner_categories: list[str] = Field(default_factory=lambda: ["person"])


def _center(obj: FrameObject) -> tuple[float, float]:
    x1, y1, x2, y2 = obj.bbox
    return ((x1 + x2) / 2, (y1 + y2) / 2)


@rule("abandoned_object")
class AbandonedObject(CameraRule):
    event_type = "abandoned_object"
    description = "A bag or suitcase has been left on its own, with no person near it."
    default_severity: Severity = "high"
    Params = AbandonedObjectParams

    def evaluate_camera(
        self,
        objects: Sequence[FrameObject],
        params: RuleParams,
        ctx: FrameContext,
        memory: dict[str, Any],
    ) -> list[Hit]:
        assert isinstance(params, AbandonedObjectParams)  # noqa: S101 - type narrowing only
        now = ctx.ts.timestamp()
        owners = [_center(o) for o in objects if o.category in params.owner_categories]
        hits: list[Hit] = []

        for obj in objects:
            if obj.category not in params.categories:
                continue
            cx, cy = _center(obj)
            entry = memory.get(obj.track_id)
            moved = entry is not None and (
                math.hypot(cx - entry["anchor"][0], cy - entry["anchor"][1]) > params.static_epsilon
            )
            vanished = entry is not None and now - entry["last_seen"] > params.debounce_s
            if entry is None or moved or vanished:
                # Newly seen, picked up, or gone long enough that we lost it: start over.
                entry = {
                    "anchor": [cx, cy],
                    "static_since": now,
                    "last_seen": now,
                    "unattended_since": None,
                }
                memory[obj.track_id] = entry
            entry["last_seen"] = now

            if any(math.hypot(ox - cx, oy - cy) <= params.owner_radius for ox, oy in owners):
                entry["unattended_since"] = None
            elif entry["unattended_since"] is None:
                entry["unattended_since"] = now

            unattended_since = entry["unattended_since"]
            if unattended_since is None:
                continue
            static_for = now - entry["static_since"]
            unattended_for = now - unattended_since
            if static_for >= params.static_s and unattended_for >= params.unattended_s:
                hits.append(
                    Hit(
                        key=obj.track_id,
                        track_ids=(obj.track_id,),
                        score=obj.conf,
                        metrics={"static_s": static_for, "unattended_s": unattended_for},
                        since=datetime.fromtimestamp(unattended_since, tz=UTC),
                    )
                )

        # Forget objects not seen for longer than they could still be tracked as the same one.
        for track_id in [t for t, e in memory.items() if now - e["last_seen"] > params.debounce_s]:
            del memory[track_id]
        return hits
