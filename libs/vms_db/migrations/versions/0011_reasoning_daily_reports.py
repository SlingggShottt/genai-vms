"""reasoning schema: daily_reports

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("facts", postgresql.JSONB(), nullable=True),
        sa.Column("narrative", sa.Text(), nullable=True),
        sa.Column("narrative_source", sa.String(length=20), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_reports")),
        sa.CheckConstraint(
            "status IN ('queued', 'generating', 'ready', 'failed')",
            name=op.f("ck_daily_reports_status"),
        ),
        sa.CheckConstraint("date_to >= date_from", name=op.f("ck_daily_reports_range")),
        schema="reasoning",
    )
    op.create_index(
        "ix_reasoning_daily_reports_created_at", "daily_reports", ["created_at"], schema="reasoning"
    )


def downgrade() -> None:
    op.drop_table("daily_reports", schema="reasoning")
