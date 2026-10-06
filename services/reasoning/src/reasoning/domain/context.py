"""What one reasoning job is about: its events, cameras and time window. Pure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from vms_common.contracts.event import Severity
from vms_common.contracts.reasoning import Window

from reasoning.adapters.store import SEVERITY_ORDER, EventInfo

CLAIMS: dict[str, str] = {
    "intrusion": "a person is inside an area they should not be in",
    "loitering": "a person is staying in the same area for an unusually long time",
    "crowding": "an unusually large number of people are gathered together",
    "running": "a person is running",
    "abandoned_object": "an object has been left behind with nobody near it",
}


@dataclass(frozen=True)
class Context:
    group_id: str | None
    events: list[EventInfo]
    primary: EventInfo
    severity: Severity
    event_type: str
    cameras: list[str]  # primary camera first, at most `max_views`
    all_cameras: list[str]
    window: Window

    @property
    def claim(self) -> str:
        base = CLAIMS.get(self.event_type, f"a {self.event_type.replace('_', ' ')} is happening")
        zone = f" ({self.primary.zone_name})" if self.primary.zone_name else ""
        return base + zone


def build_context(
    events: list[EventInfo],
    *,
    group_id: str | None,
    pad_before_s: float,
    pad_after_s: float,
    max_views: int,
) -> Context | None:
    if not events:
        return None
    primary = max(events, key=lambda e: (SEVERITY_ORDER.index(e.severity), -e.start.timestamp()))
    counts: dict[str, int] = {}
    for e in events:
        counts[e.camera_id] = counts.get(e.camera_id, 0) + 1
    others = sorted((c for c in counts if c != primary.camera_id), key=lambda c: -counts[c])
    all_cams = [primary.camera_id, *others]
    start = min(e.start for e in events) - timedelta(seconds=pad_before_s)
    end = max(e.end for e in events) + timedelta(seconds=pad_after_s)
    top = max(events, key=lambda e: SEVERITY_ORDER.index(e.severity))
    return Context(
        group_id=group_id,
        events=events,
        primary=primary,
        severity=top.severity,  # type: ignore[arg-type]
        event_type=primary.event_type,
        cameras=all_cams[:max_views],
        all_cameras=all_cams,
        window=Window(start=start, end=end),
    )


def rel(ts: datetime, origin: datetime) -> float:
    return round((ts - origin).total_seconds(), 1)
