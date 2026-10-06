"""reasoning schema (jobs, incidents) and retrieval schema (search_logs)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS reasoning")
    op.execute("CREATE SCHEMA IF NOT EXISTS retrieval")

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_ids", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(length=50), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')", name=op.f("ck_jobs_status")
        ),
        sa.CheckConstraint("trigger IN ('auto', 'manual')", name=op.f("ck_jobs_trigger")),
        schema="reasoning",
    )
    op.create_index(
        "ix_reasoning_jobs_status_created_at",
        "jobs",
        ["status", "created_at"],
        schema="reasoning",
    )
    op.create_index(
        "ux_reasoning_jobs_active_group",
        "jobs",
        ["group_id"],
        unique=True,
        schema="reasoning",
        postgresql_where=sa.text("group_id IS NOT NULL AND status IN ('queued', 'running')"),
    )

    op.create_table(
        "incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_ids", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("camera_ids", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("report", postgresql.JSONB(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.Column("provenance", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("raw_output", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incidents")),
        sa.CheckConstraint(
            "status IN ('generating', 'generated', 'failed', 'reviewed', 'closed')",
            name=op.f("ck_incidents_status"),
        ),
        schema="reasoning",
    )
    op.create_index(
        "ix_reasoning_incidents_created_at", "incidents", ["created_at"], schema="reasoning"
    )
    op.create_index(
        "ix_reasoning_incidents_group_id", "incidents", ["group_id"], schema="reasoning"
    )

    op.create_table(
        "search_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("profile", sa.String(length=20), nullable=False),
        sa.Column("plan", postgresql.JSONB(), nullable=True),
        sa.Column("results", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("timings", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_search_logs")),
        schema="retrieval",
    )
    op.create_index(
        "ix_retrieval_search_logs_created_at", "search_logs", ["created_at"], schema="retrieval"
    )


def downgrade() -> None:
    op.drop_table("search_logs", schema="retrieval")
    op.drop_table("incidents", schema="reasoning")
    op.drop_table("jobs", schema="reasoning")
    op.execute("DROP SCHEMA IF EXISTS retrieval")
    op.execute("DROP SCHEMA IF EXISTS reasoning")
