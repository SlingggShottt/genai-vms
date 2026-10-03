"""events schema: correlation_groups, correlation_links

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS events")  # created by 0004; harmless if already there

    op.create_table(
        "correlation_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("start_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_severity", sa.String(length=20), nullable=False),
        sa.Column("camera_ids", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("event_types", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("event_ids", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("members", postgresql.JSONB(), nullable=False),
        sa.Column("merged_into", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("publish_pending", sa.Boolean(), nullable=False),
        sa.Column("last_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_correlation_groups")),
        sa.ForeignKeyConstraint(
            ["merged_into"],
            ["events.correlation_groups.id"],
            name=op.f("fk_correlation_groups_merged_into_correlation_groups"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'closed', 'merged')", name=op.f("ck_correlation_groups_status")
        ),
        sa.CheckConstraint(
            "max_severity IN ('low', 'medium', 'high', 'critical')",
            name=op.f("ck_correlation_groups_max_severity"),
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_correlation_groups_revision")),
        sa.CheckConstraint("end_ts >= start_ts", name=op.f("ck_correlation_groups_window")),
        sa.CheckConstraint(
            "(status = 'merged') = (merged_into IS NOT NULL)",
            name=op.f("ck_correlation_groups_merged_into"),
        ),
        sa.CheckConstraint(
            "cardinality(event_ids) >= 1", name=op.f("ck_correlation_groups_has_events")
        ),
        schema="events",
    )
    op.create_index(
        "ix_events_correlation_groups_open",
        "correlation_groups",
        ["site_id"],
        schema="events",
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_events_correlation_groups_publish_pending",
        "correlation_groups",
        ["created_at"],
        schema="events",
        postgresql_where=sa.text("publish_pending"),
    )
    op.create_index(
        "ix_events_correlation_groups_event_ids",
        "correlation_groups",
        ["event_ids"],
        schema="events",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_events_correlation_groups_start_ts", "correlation_groups", ["start_ts"], schema="events"
    )

    op.create_table(
        "correlation_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_event", sa.Text(), nullable=False),
        sa.Column("to_event", sa.Text(), nullable=False),
        sa.Column("edge_type", sa.String(length=20), nullable=False),
        sa.Column("delta_s", sa.Float(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_correlation_links")),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["events.correlation_groups.id"],
            name=op.f("fk_correlation_links_group_id_correlation_groups"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "edge_type IN ('overlap', 'transit')", name=op.f("ck_correlation_links_edge_type")
        ),
        sa.CheckConstraint("score >= 0 AND score <= 1", name=op.f("ck_correlation_links_score")),
        sa.UniqueConstraint("from_event", "to_event", name=op.f("uq_correlation_links_pair")),
        schema="events",
    )
    op.create_index(
        "ix_events_correlation_links_group_id", "correlation_links", ["group_id"], schema="events"
    )


def downgrade() -> None:
    op.drop_table("correlation_links", schema="events")
    op.drop_table("correlation_groups", schema="events")
    # the `events` schema belongs to 0004 (candidates): leave it for that migration to drop
