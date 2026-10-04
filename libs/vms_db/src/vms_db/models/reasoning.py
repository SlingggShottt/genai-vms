"""ORM models for the `reasoning` schema — the reasoning job queue and incident reports
(design_architecture.md §6.1, §8). Owner: D.

`reasoning.jobs` is a Postgres-backed queue (`FOR UPDATE SKIP LOCKED`): the api inserts a row
when an operator presses *Analyze*, the reasoning service inserts one when a correlation group
closes at or above its severity threshold, and the worker claims them one at a time.
`reasoning.incidents` holds the finished report (`incident.v1` as JSONB) together with the
evidence bundle (`evidence.v1`) it cites.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from vms_db.base import Base

SCHEMA = "reasoning"

JOB_STATUSES = ("queued", "running", "done", "failed")
JOB_TRIGGERS = ("auto", "manual")
INCIDENT_STATUSES = ("generating", "generated", "failed", "reviewed", "closed")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class ReasoningJob(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(_in_list("status", JOB_STATUSES), name="status"),
        CheckConstraint(_in_list("trigger", JOB_TRIGGERS), name="trigger"),
        Index("ix_reasoning_jobs_status_created_at", "status", "created_at"),
        # One live job per correlation group: pressing Analyze twice (or a group re-closing)
        # must not queue the same work twice.
        Index(
            "ux_reasoning_jobs_active_group",
            "group_id",
            unique=True,
            postgresql_where=text("group_id IS NOT NULL AND status IN ('queued', 'running')"),
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    event_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="queued")
    stage: Mapped[str] = mapped_column(String(50), nullable=False, server_default="queued")
    progress: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # A running job whose worker died is re-claimable once this passes.
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint(_in_list("status", INCIDENT_STATUSES), name="status"),
        Index("ix_reasoning_incidents_created_at", "created_at"),
        Index("ix_reasoning_incidents_group_id", "group_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    event_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    camera_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # incident.v1
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # evidence.v1
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)  # kept when status=failed
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
