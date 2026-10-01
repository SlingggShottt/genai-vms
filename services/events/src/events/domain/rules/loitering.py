"""`loitering` — the same track stays in a zone longer than `dwell_s`
(design_architecture.md §7.3; default 60 s, severity medium).

Per frame this only says "this person is in this zone"; the dwell time is the
length of the (debounced) episode, which the engine tracks across frames and
segments — so a person who steps out for longer than `debounce_s` starts a
fresh dwell clock.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import Field
from vms_common.contracts.twin import FrameObject
from vms_common.contracts.zones import ZoneInternal

from events.domain.rules.base import (
    ALL_ZONE_TYPES,
    FrameContext,
    Hit,
    Rule,
    RuleParams,
    Severity,
    ZoneType,
    rule,
)


class LoiteringParams(RuleParams):
    dwell_s: float = Field(
        default=60.0, gt=0, description="Time in the zone before it's loitering."
    )
    categories: list[str] = Field(default_factory=lambda: ["person"])
    zone_types: list[ZoneType] = Field(default_factory=lambda: list(ALL_ZONE_TYPES))

    def required_duration_s(self) -> float:
        return self.dwell_s


@rule("loitering")
class Loitering(Rule):
    event_type = "loitering"
    default_severity: Severity = "medium"
    Params = LoiteringParams

    def evaluate(
        self,
        zone: ZoneInternal,
        objects: Sequence[FrameObject],
        params: RuleParams,
        ctx: FrameContext,
    ) -> list[Hit]:
        assert isinstance(params, LoiteringParams)  # noqa: S101 - type narrowing only
        if zone.zone_type not in params.zone_types:
            return []
        return [
            Hit(key=obj.track_id, track_ids=(obj.track_id,), score=obj.conf)
            for obj in objects
            if obj.category in params.categories
        ]
