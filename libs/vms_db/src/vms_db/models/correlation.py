"""ORM models for the correlation tables of the `events` schema
(design_architecture.md §6.1, §7.5). Owner: J. Written by the correlation service (P3-J2).

A *group* is a set of events linked across cameras by the camera graph and by time (or one
event nothing linked to). Its members are kept on the row itself (`members` JSONB, a
snapshot of what linking needs) so the engine can decide everything about an open group from
that one row; `event_ids` repeats the ids in a GIN-indexed array to answer "which group holds
this event?" — the idempotency check for a redelivered `event.v1`.

`status` only moves open -> closed or open -> merged, both final. `revision` increases with
every change; the service writes a group only if its revision is newer than the stored one, so
a stale writer can never overwrite newer state. `publish_pending` is true from a change until
the matching `correlation.v1` has been sent, which is what lets a crash between the write and
the send be recovered: the next sweep sends it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from vms_common.ids import uuid7

from vms_db.base import Base

SCHEMA = "events"

GROUP_STATUSES = ("open", "closed", "merged")
SEVERITIES = ("low", "medium", "high", "critical")
LINK_EDGE_TYPES = ("overlap", "transit")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class CorrelationGroup(Base):
    __tablename__ = "correlation_groups"
    __table_args__ = (
        CheckConstraint(_in_list("status", GROUP_STATUSES), name="status"),
        CheckConstraint(_in_list("max_severity", SEVERITIES), name="max_severity"),
        CheckConstraint("revision >= 1", name="revision"),
        CheckConstraint("end_ts >= start_ts", name="window"),
        CheckConstraint("(status = 'merged') = (merged_into IS NOT NULL)", name="merged_into"),
        CheckConstraint("cardinality(event_ids) >= 1", name="has_events"),
        Index(
            "ix_events_correlation_groups_open",
            "site_id",
            postgresql_where=text("status = 'open'"),
        ),
        Index(
            "ix_events_correlation_groups_publish_pending",
            "created_at",
            postgresql_where=text("publish_pending"),
        ),
        Index("ix_events_correlation_groups_event_ids", "event_ids", postgresql_using="gin"),
        Index("ix_events_correlation_groups_start_ts", "start_ts"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    site_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_severity: Mapped[str] = mapped_column(String(20), nullable=False)
    camera_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    event_types: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    event_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    members: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    merged_into: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        # CASCADE, not SET NULL: a merged group is only the history of its survivor, and SET NULL
        # would leave a 'merged' row with no survivor — which the CHECK above forbids.
        ForeignKey(f"{SCHEMA}.correlation_groups.id", ondelete="CASCADE"),
        nullable=True,
    )
    publish_pending: Mapped[bool] = mapped_column(Boolean, nullable=False)
    last_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CorrelationLinkRow(Base):
    """`events.correlation_links` — why two events share a group. `(from_event, to_event)` is
    unique so a redelivered event cannot record its links twice; when groups merge the links
    are re-pointed at the surviving group (`group_id` is updated), never duplicated."""

    __tablename__ = "correlation_links"
    __table_args__ = (
        CheckConstraint(_in_list("edge_type", LINK_EDGE_TYPES), name="edge_type"),
        CheckConstraint("score >= 0 AND score <= 1", name="score"),
        UniqueConstraint("from_event", "to_event", name="uq_correlation_links_pair"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.correlation_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_event: Mapped[str] = mapped_column(Text, nullable=False)
    to_event: Mapped[str] = mapped_column(Text, nullable=False)
    edge_type: Mapped[str] = mapped_column(String(20), nullable=False)
    delta_s: Mapped[float] = mapped_column(Float, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
