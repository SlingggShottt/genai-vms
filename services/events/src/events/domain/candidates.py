"""The candidate record the engine emits, and its deterministic id — pure."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

# Fixed namespace for candidate ids. Never change it: ids must stay stable
# across restarts and versions so a replayed twin upserts the same row.
CANDIDATE_NAMESPACE = uuid.UUID("5b0f1c52-6b1f-4c0e-9a4e-3f7a8d1e2c90")

CandidateStatus = Literal["open", "closed"]


def candidate_id(
    camera_id: str, rule_id: str, zone_name: str, hit_key: str, start_ts: datetime
) -> uuid.UUID:
    """Deterministic id for one episode (design §15 idempotency key
    `(camera_id, rule_id, track_id, start_ts)`, plus the zone so one track in
    two zones is two candidates). Same inputs -> same id, on any machine."""
    start = start_ts.astimezone(UTC).isoformat(timespec="microseconds")
    return uuid.uuid5(CANDIDATE_NAMESPACE, f"{camera_id}|{rule_id}|{zone_name}|{hit_key}|{start}")


@dataclass(frozen=True)
class CandidateUpdate:
    """The latest known state of one candidate, to upsert into `events.candidates`."""

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
    status: CandidateStatus
    details: dict[str, Any] = field(default_factory=dict)
