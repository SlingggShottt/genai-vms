"""retrieval schema: chat_sessions and chat_messages (assistant memory)

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default="New conversation"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("summarized_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_sessions")),
        schema="retrieval",
    )
    op.create_index(
        "ix_retrieval_chat_sessions_user_id_updated_at",
        "chat_sessions",
        ["user_id", "updated_at"],
        schema="retrieval",
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("tools", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="complete"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["retrieval.chat_sessions.id"],
            name=op.f("fk_chat_messages_session_id_chat_sessions"),
            ondelete="CASCADE",
        ),
        schema="retrieval",
    )
    op.create_index(
        "ix_retrieval_chat_messages_session_id_created_at",
        "chat_messages",
        ["session_id", "created_at"],
        schema="retrieval",
    )


def downgrade() -> None:
    op.drop_table("chat_messages", schema="retrieval")
    op.drop_table("chat_sessions", schema="retrieval")
