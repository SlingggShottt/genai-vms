"""`intrusion.restricted` — a person or vehicle inside a `restricted` zone
(design_architecture.md §7.3; default `min_frames: 2`, severity high)."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import Field
from vms_common.contracts.twin import FrameObject
from vms_common.contracts.zones import ZoneInternal

from events.domain.rules.base import (
    VEHICLE_CATEGORIES,
    FrameContext,
    Hit,
    RuleParams,
    Severity,
    ZoneRule,
    rule,
)


class IntrusionRestrictedParams(RuleParams):
    min_frames: int = Field(
        default=2, ge=1, description="Consecutive-ish sampled frames before it becomes a candidate."
    )
    categories: list[str] = Field(default_factory=lambda: ["person", *VEHICLE_CATEGORIES])

    def required_frames(self) -> int:
        return self.min_frames


@rule("intrusion.restricted")
class IntrusionRestricted(ZoneRule):
    event_type = "intrusion"
    description = "A person or vehicle is inside a restricted area."
    default_severity: Severity = "high"
    Params = IntrusionRestrictedParams

    def evaluate(
        self,
        zone: ZoneInternal,
        objects: Sequence[FrameObject],
        params: RuleParams,
        ctx: FrameContext,
    ) -> list[Hit]:
        assert isinstance(params, IntrusionRestrictedParams)  # noqa: S101 - type narrowing only
        if zone.zone_type != "restricted":
            return []
        return [
            Hit(key=obj.track_id, track_ids=(obj.track_id,), score=obj.conf)
            for obj in objects
            if obj.category in params.categories
        ]
