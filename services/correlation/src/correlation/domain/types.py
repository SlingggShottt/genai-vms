"""In-memory shapes the correlation engine works on — plain dataclasses, no I/O.

`EventRecord` is the slice of `event.v1` linking needs; `Group` is one correlation group
and carries its members and links, so the engine can decide everything about an open
group from the group alone (and the persisted row is just this, serialised).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from vms_common.contracts.event import SEVERITY_ORDER

GroupStatus = Literal["open", "closed", "merged"]


@dataclass(frozen=True)
class EventRecord:
    event_id: str
    site_id: str
    camera_id: str
    event_type: str
    severity: str
    start_ts: datetime
    end_ts: datetime


@dataclass(frozen=True)
class LinkRecord:
    """Why two events share a group. For `transit`, `from_event` is the event on the edge's
    `from` camera and `delta_s` is start(to-event) - end(from-event); for `overlap`,
    `from_event` is the event that was already in the group and `delta_s` is the gap between
    the two windows (0 when they intersect)."""

    from_event: str
    to_event: str
    edge_type: Literal["overlap", "transit"]
    delta_s: float
    score: float


@dataclass
class Group:
    id: str
    site_id: str
    created_at: datetime
    members: list[EventRecord]
    status: GroupStatus = "open"
    revision: int = 1
    links: list[LinkRecord] = field(default_factory=list)
    closed_at: datetime | None = None
    merged_into: str | None = None
    # True from any change until the change has been published; see `engine.due_for_publish`.
    publish_pending: bool = True
    last_published_at: datetime | None = None

    @property
    def event_ids(self) -> list[str]:
        return [m.event_id for m in self.members]

    @property
    def start_ts(self) -> datetime:
        return min(m.start_ts for m in self.members)

    @property
    def end_ts(self) -> datetime:
        return max(m.end_ts for m in self.members)

    @property
    def camera_ids(self) -> list[str]:
        return sorted({m.camera_id for m in self.members})

    @property
    def event_types(self) -> list[str]:
        return sorted({m.event_type for m in self.members})

    @property
    def max_severity(self) -> str:
        return max((m.severity for m in self.members), key=SEVERITY_ORDER.index)
