"""`intrusion.after_hours` — a person in a zone outside that zone's schedule
(design_architecture.md §7.3, severity high).

Applies to any zone that has a `schedule`, whatever its type. A zone with no
schedule can never be "outside" it, so the rule stays silent there.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import Field
from vms_common.contracts.twin import FrameObject
from vms_common.contracts.zones import ZoneInternal
from vms_common.logging import get_logger

from events.domain.rules.base import FrameContext, Hit, RuleParams, Severity, ZoneRule, rule
from events.domain.schedule import is_within_schedule

log = get_logger(__name__)


class IntrusionAfterHoursParams(RuleParams):
    # Not in the design table (its only parameter is the per-zone schedule);
    # added so a single mis-detected frame can't raise a high-severity candidate.
    min_frames: int = Field(default=2, ge=1)
    categories: list[str] = Field(default_factory=lambda: ["person"])

    def required_frames(self) -> int:
        return self.min_frames


@rule("intrusion.after_hours")
class IntrusionAfterHours(ZoneRule):
    event_type = "intrusion"
    default_severity: Severity = "high"
    Params = IntrusionAfterHoursParams

    def evaluate(
        self,
        zone: ZoneInternal,
        objects: Sequence[FrameObject],
        params: RuleParams,
        ctx: FrameContext,
    ) -> list[Hit]:
        assert isinstance(params, IntrusionAfterHoursParams)  # noqa: S101 - type narrowing only
        if zone.schedule is None:
            return []
        try:
            inside_schedule = is_within_schedule(zone.schedule, ctx.local_time)
        except ValueError as exc:
            # A malformed schedule must not turn into "always after hours".
            log.warning(
                "zone_schedule_invalid", zone=zone.name, camera_id=ctx.camera_id, error=str(exc)
            )
            return []
        if inside_schedule:
            return []
        return [
            Hit(key=obj.track_id, track_ids=(obj.track_id,), score=obj.conf)
            for obj in objects
            if obj.category in params.categories
        ]
