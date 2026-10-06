"""events schema: events (the VLM gate's decisions) and the gate's queue columns on candidates

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidates",
        sa.Column("verify_attempts", sa.Integer(), nullable=False, server_default="0"),
        schema="events",
    )
    op.add_column(
        "candidates",
        sa.Column("verify_first_at", sa.DateTime(timezone=True), nullable=True),
        schema="events",
    )
    op.add_column(
        "candidates",
        sa.Column("verify_not_before", sa.DateTime(timezone=True), nullable=True),
        schema="events",
    )

    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", sa.String(length=100), nullable=False),
        sa.Column("camera_id", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("rule_id", sa.String(length=100), nullable=False),
        sa.Column("rule_score", sa.Float(), nullable=False),
        sa.Column("zone_id", sa.Text(), nullable=True),
        sa.Column("zone_name", sa.Text(), nullable=True),
        sa.Column("track_ids", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("segment_ids", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column(
            "keyframe_uris", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column("start_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("verification", postgresql.JSONB(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
        sa.CheckConstraint(
            "status IN ('verified', 'skipped', 'rejected')", name=op.f("ck_events_status")
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')", name=op.f("ck_events_severity")
        ),
        sa.CheckConstraint("end_ts >= start_ts", name=op.f("ck_events_window")),
        sa.CheckConstraint(
            "rule_score >= 0 AND rule_score <= 1", name=op.f("ck_events_rule_score")
        ),
        sa.CheckConstraint(
            "status <> 'rejected' OR published_at IS NULL",
            name=op.f("ck_events_rejected_unpublished"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(verification) = 'object'", name=op.f("ck_events_verification_object")
        ),
        schema="events",
    )
    op.create_index(
        "ix_events_events_camera_id_start_ts",
        "events",
        ["camera_id", "start_ts"],
        schema="events",
    )
    op.create_index(
        "ix_events_events_publish_pending",
        "events",
        ["created_at"],
        schema="events",
        postgresql_where=sa.text("status IN ('verified', 'skipped') AND published_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("events", schema="events")
    op.drop_column("candidates", "verify_not_before", schema="events")
    op.drop_column("candidates", "verify_first_at", schema="events")
    op.drop_column("candidates", "verify_attempts", schema="events")
