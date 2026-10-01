"""`crowding` — more than `max_persons` people in a zone for longer than
`duration_s` (design_architecture.md §7.3; defaults N = 8, T = 20 s,
severity medium).

Per frame this says "the zone holds more than N people right now"; holding it
for T is the engine's duration threshold. The hit is zone-wide (key `"*"`), so
one crowd is one candidate however individual tracks come and go.
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


class CrowdingParams(RuleParams):
    max_persons: int = Field(default=8, ge=1, description="Crowded means strictly more than this.")
    duration_s: float = Field(default=20.0, ge=0, description="How long it must stay crowded.")
    categories: list[str] = Field(default_factory=lambda: ["person"])
    zone_types: list[ZoneType] = Field(default_factory=lambda: list(ALL_ZONE_TYPES))

    def required_duration_s(self) -> float:
        return self.duration_s


@rule("crowding")
class Crowding(Rule):
    event_type = "crowding"
    default_severity: Severity = "medium"
    Params = CrowdingParams

    def evaluate(
        self,
        zone: ZoneInternal,
        objects: Sequence[FrameObject],
        params: RuleParams,
        ctx: FrameContext,
    ) -> list[Hit]:
        assert isinstance(params, CrowdingParams)  # noqa: S101 - type narrowing only
        if zone.zone_type not in params.zone_types:
            return []
        present = sorted({obj.track_id for obj in objects if obj.category in params.categories})
        count = len(present)
        if count <= params.max_persons:
            return []
        return [
            Hit(
                key="*",
                track_ids=tuple(present),
                # Heuristic, uncalibrated: just over the limit ~0.5, double the limit 1.0.
                score=min(1.0, count / (2 * params.max_persons)),
                metrics={"count": float(count)},
            )
        ]
