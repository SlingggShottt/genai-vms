"""ORM models for the `retrieval` schema (design_architecture.md §6.1). Owner: D.

`retrieval.search_logs` records every search with its plan, candidates and per-stage timings, so
the evaluation harness (P4-J6) can replay and score them.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
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


class ChatSession(Base):
    """`retrieval.chat_sessions` — one assistant conversation (design §10.3, FR-AST-01).

    `summary` is the rolling summary of everything older than the last 12 messages;
    `summarized_count` is how many messages it already covers.
    """

    __tablename__ = "chat_sessions"
    __table_args__ = (
        Index("ix_retrieval_chat_sessions_user_id_updated_at", "user_id", "updated_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, server_default="New conversation")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summarized_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ChatMessage(Base):
    """`retrieval.chat_messages` — one turn. An assistant turn keeps the evidence it cited and the
    tools it ran (their arguments and a one-line summary, never the raw results)."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_retrieval_chat_messages_session_id_created_at", "session_id", "created_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("retrieval.chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    tools: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="complete")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
