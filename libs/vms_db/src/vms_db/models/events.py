"""ORM models for the `events` schema — rule-engine candidates
(design_architecture.md §6.1, §7.3). Owner: D. Written by the events service
(P3-D1). `events.events` (what the VLM gate decided about each candidate) is written by the same
service (P3-D4).

A *candidate* is one rule hit episode before VLM verification: the same
`(camera, rule, zone, track)` seen across consecutive samples (and segments),
debounced into a single row that extends while the condition holds
(design §7.3 "Candidates are debounced per (camera, rule, track); an open
candidate extends while the condition holds").
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from vms_common.types import CameraCode

from vms_db.base import Base

SCHEMA = "events"

CANDIDATE_STATUSES = ("open", "closed")
CANDIDATE_SEVERITIES = ("low", "medium", "high", "critical")
EVENT_STATUSES = ("verified", "skipped", "rejected")


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
    # The VLM gate's work queue (P3-D4): a candidate is waiting while no `events.events` row has
    # its id. `verify_not_before` is both the lease a worker takes on it and the back-off after a
    # failed try; `verify_first_at` dates the first try so a held candidate can be given up on.
    verify_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    verify_first_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verify_not_before: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Event(Base):
    """`events.events` — what the VLM gate decided about one candidate (design §6.1, §7.4).

    `id` is the candidate's id: one decision per candidate, and a retried verification writes the
    same row (`ON CONFLICT DO NOTHING`). `status`:

    * `verified` — the VLM confirmed it (or accepted it as `unsure` for a low-severity rule);
    * `skipped` — not asked (`verify: false`) or could not be asked (gateway down, see the
      events README); published all the same, flagged unverified;
    * `rejected` — the VLM said no, or `unsure` for a rule whose severity does not accept that.
      Stored with its reason in `verification`, never published.

    `published_at` is the outbox marker: a `verified`/`skipped` row without it is waiting to be
    announced as `event.v1`, so a crash between the insert and the send loses nothing.
    """

    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(_in_list("status", EVENT_STATUSES), name="status"),
        CheckConstraint(_in_list("severity", CANDIDATE_SEVERITIES), name="severity"),
        CheckConstraint("end_ts >= start_ts", name="window"),
        CheckConstraint("rule_score >= 0 AND rule_score <= 1", name="rule_score"),
        CheckConstraint(
            "status <> 'rejected' OR published_at IS NULL", name="rejected_unpublished"
        ),
        # A Python None in a JSONB column is stored as JSON `null`, which NOT NULL lets through.
        CheckConstraint("jsonb_typeof(verification) = 'object'", name="verification_object"),
        Index("ix_events_events_camera_id_start_ts", "camera_id", "start_ts"),
        Index(
            "ix_events_events_publish_pending",
            "created_at",
            postgresql_where=text("status IN ('verified', 'skipped') AND published_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    site_id: Mapped[str] = mapped_column(String(100), nullable=False)
    camera_id: Mapped[CameraCode] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False)
    rule_score: Mapped[float] = mapped_column(Float, nullable=False)
    zone_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    zone_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    track_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    segment_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    keyframe_uris: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    verification: Mapped[dict] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
