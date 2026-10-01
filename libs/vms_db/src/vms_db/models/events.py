"""ORM models for the `events` schema — rule-engine candidates
(design_architecture.md §6.1, §7.3). Owner: D. Written by the events service
(P3-D1); `events.events` (verified events) lands with P3-D4.

A *candidate* is one rule hit episode before VLM verification: the same
`(camera, rule, zone, track)` seen across consecutive samples (and segments),
debounced into a single row that extends while the condition holds
(design §7.3 "Candidates are debounced per (camera, rule, track); an open
candidate extends while the condition holds").
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, Index, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from vms_common.types import CameraCode

from vms_db.base import Base

SCHEMA = "events"

CANDIDATE_STATUSES = ("open", "closed")
CANDIDATE_SEVERITIES = ("low", "medium", "high", "critical")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Candidate(Base):
    """`events.candidates` — one row per rule-hit episode.

    `id` is deterministic (derived from camera, rule, zone, track and start
    time by the events service) so replaying a `twinready.v1` message is an
    idempotent upsert rather than a duplicate (CLAUDE.md: Kafka consumers do
    an idempotent write; design §15 idempotency key
    `(camera_id, rule_id, track_id, start_ts)`).

    `status` is `open` while the condition may still hold and `closed` once it
    has been quiet longer than the rule's debounce window; it only ever moves
    open -> closed. `zone_id` is text, not a FK: zones come from the internal
    API or the YAML fallback, whose ids are not always `core.zones` UUIDs.
    """

    __tablename__ = "candidates"
    __table_args__ = (
        CheckConstraint(_in_list("status", CANDIDATE_STATUSES), name="status"),
        CheckConstraint(_in_list("severity", CANDIDATE_SEVERITIES), name="severity"),
        Index("ix_events_candidates_camera_id_start_ts", "camera_id", "start_ts"),
        Index("ix_events_candidates_status", "status"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    site_id: Mapped[str] = mapped_column(String(100), nullable=False)
    camera_id: Mapped[CameraCode] = mapped_column(String(100), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    zone_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    zone_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    track_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    segment_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rule_score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
