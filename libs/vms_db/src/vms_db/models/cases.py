"""ORM models for investigation cases (`core.cases`, `core.case_items`; design §6.1, FR-INV-03).

A case is a named collection of things an operator wants to keep together while investigating:
events, incident reports, moments of footage, search queries and free notes. Cases are shared
across operators (an investigation is handed over, not owned); `owner_id` records who opened it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from vms_db.base import Base

SCHEMA = "core"
CASE_STATUSES = ("open", "closed")
ITEM_KINDS = ("event", "incident", "footage", "search", "note")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        CheckConstraint(_in_list("status", CASE_STATUSES), name="status"),
        Index("ix_core_cases_updated_at", "updated_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CaseItem(Base):
    """One bookmarked thing. `ref` is what `kind` points at (an event id, an incident id, a
    segment id, the search text); `camera_id`/`ts_start`/`ts_end` locate footage and events so a
    case can be replayed; `note` is the investigator's remark about this item."""

    __tablename__ = "case_items"
    __table_args__ = (
        CheckConstraint(_in_list("kind", ITEM_KINDS), name="kind"),
        Index("ix_core_case_items_case_id_created_at", "case_id", "created_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.cases.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    camera_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ts_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ts_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
