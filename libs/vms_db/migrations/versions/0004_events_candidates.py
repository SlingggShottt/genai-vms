"""events schema: candidates

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS events")

    op.create_table(
        "candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", sa.String(length=100), nullable=False),
        sa.Column("camera_id", sa.String(length=100), nullable=False),
        sa.Column("rule_id", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("zone_id", sa.Text(), nullable=True),
        sa.Column("zone_name", sa.Text(), nullable=True),
        sa.Column("track_ids", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("segment_ids", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("start_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rule_score", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidates")),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name=op.f("ck_candidates_severity"),
        ),
        sa.CheckConstraint("status IN ('open', 'closed')", name=op.f("ck_candidates_status")),
        schema="events",
    )
    op.create_index(
        "ix_events_candidates_camera_id_start_ts",
        "candidates",
        ["camera_id", "start_ts"],
        schema="events",
    )
    op.create_index("ix_events_candidates_status", "candidates", ["status"], schema="events")


def downgrade() -> None:
    op.drop_table("candidates", schema="events")
    op.execute("DROP SCHEMA IF EXISTS events")
