"""ORM models for the `retrieval` schema (design_architecture.md §6.1). Owner: D.

`retrieval.search_logs` records every search with its plan, candidates and per-stage timings, so
the evaluation harness (P4-J6) can replay and score them.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from vms_db.base import Base

SCHEMA = "retrieval"


class SearchLog(Base):
    __tablename__ = "search_logs"
    __table_args__ = (
        Index("ix_retrieval_search_logs_created_at", "created_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # text | image
    query: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    profile: Mapped[str] = mapped_column(String(20), nullable=False)
    plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    results: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    timings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
