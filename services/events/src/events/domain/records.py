"""The two records the VLM gate passes around (P3-D4): a candidate waiting to be judged and the
event row that records the judgement. Plain data — the store maps them to and from Postgres."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from events.domain.evidence import EvidenceFrame, evidence_of


@dataclass(frozen=True)
class PendingCandidate:
    """A candidate the gate has claimed. `attempts` counts this try (>= 1); `first_at` is when
    the gate first took it, so a candidate that keeps failing can be given up on."""

    id: uuid.UUID
    site_id: str
    camera_id: str
    rule_id: str
    event_type: str
    severity: str
    zone_id: str | None
    zone_name: str | None
    track_ids: list[str]
    segment_ids: list[str]
    start_ts: datetime
    end_ts: datetime
    rule_score: float
    status: str  # open | closed: the gate also judges candidates that are still going
    details: dict[str, Any]
    attempts: int
    first_at: datetime

    @property
    def evidence(self) -> list[EvidenceFrame]:
        return evidence_of(self.details)


@dataclass(frozen=True)
class EventRow:
    """What the gate decided about one candidate (`events.events`)."""

    id: uuid.UUID
    site_id: str
    camera_id: str
    event_type: str
    severity: str
    rule_id: str
    rule_score: float
    zone_id: str | None
    zone_name: str | None
    track_ids: list[str]
    segment_ids: list[str]
    keyframe_uris: list[str]
    start_ts: datetime
    end_ts: datetime
    status: str  # verified | skipped | rejected
    verification: dict[str, Any] = field(default_factory=dict)
