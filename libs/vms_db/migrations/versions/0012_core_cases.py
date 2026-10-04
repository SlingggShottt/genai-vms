"""core schema: cases and case_items (investigations)

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cases")),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["core.users.id"],
            name=op.f("fk_cases_owner_id_users"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("status IN ('open', 'closed')", name=op.f("ck_cases_status")),
        schema="core",
    )
    op.create_index("ix_core_cases_updated_at", "cases", ["updated_at"], schema="core")
    op.create_table(
        "case_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("ref", sa.Text(), nullable=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("camera_id", sa.String(length=100), nullable=True),
        sa.Column("ts_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ts_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("added_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_items")),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["core.cases.id"],
            name=op.f("fk_case_items_case_id_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["added_by"],
            ["core.users.id"],
            name=op.f("fk_case_items_added_by_users"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "kind IN ('event', 'incident', 'footage', 'search', 'note')",
            name=op.f("ck_case_items_kind"),
        ),
        schema="core",
    )
    op.create_index(
        "ix_core_case_items_case_id_created_at",
        "case_items",
        ["case_id", "created_at"],
        schema="core",
    )


def downgrade() -> None:
    op.drop_table("case_items", schema="core")
    op.drop_table("cases", schema="core")
