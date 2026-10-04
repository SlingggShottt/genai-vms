"""core schema: alerts

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("site_id", sa.String(length=100), nullable=False),
        sa.Column("camera_id", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("rule_id", sa.String(length=100), nullable=False),
        sa.Column("zone_id", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("verification_status", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("start_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "keyframe_uris", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ack_note", sa.Text(), nullable=True),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolve_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
        sa.ForeignKeyConstraint(
            ["acknowledged_by"],
            ["core.users.id"],
            name=op.f("fk_alerts_acknowledged_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"],
            ["core.users.id"],
            name=op.f("fk_alerts_resolved_by_users"),
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("event_id", name=op.f("uq_alerts_event_id")),
        sa.CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved')", name=op.f("ck_alerts_status")
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')", name=op.f("ck_alerts_severity")
        ),
        sa.CheckConstraint(
            "(status = 'open' AND acknowledged_at IS NULL AND resolved_at IS NULL)"
            " OR (status = 'acknowledged' AND acknowledged_at IS NOT NULL AND resolved_at IS NULL)"
            " OR (status = 'resolved' AND resolved_at IS NOT NULL)",
            name=op.f("ck_alerts_lifecycle"),
        ),
        schema="core",
    )
    op.create_index(
        "ix_core_alerts_status_created_at", "alerts", ["status", "created_at"], schema="core"
    )
    op.create_index("ix_core_alerts_group_id", "alerts", ["group_id"], schema="core")
    op.create_index(
        "ix_core_alerts_camera_id_created_at", "alerts", ["camera_id", "created_at"], schema="core"
    )


def downgrade() -> None:
    op.drop_table("alerts", schema="core")
