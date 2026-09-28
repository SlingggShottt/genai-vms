"""core schema: users, refresh_tokens, cameras, audit_log

Revision ID: 0001
Revises:
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `create_type` defaults to True: SQLAlchemy creates/drops this type itself,
# hooked to the "users" table's own create/drop DDL below — do not also
# call `.create()`/`.drop()` on it directly, or the type gets created twice.
USER_ROLE_ENUM = postgresql.ENUM("admin", "operator", "viewer", name="user_role", schema="core")


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS core")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", USER_ROLE_ENUM, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        schema="core",
    )
    # `email: Mapped[str] = mapped_column(..., unique=True, index=True)` compiles
    # to a single unique index, not a separate UniqueConstraint + Index — match
    # that exactly so a future autogenerate doesn't propose renaming this.
    op.create_index("ix_core_users_email", "users", ["email"], unique=True, schema="core")

    op.create_table(
        "cameras",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("rtsp_url", sa.Text(), nullable=False),
        sa.Column("site_id", sa.String(length=100), nullable=False),
        sa.Column("location_label", sa.String(length=200), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cameras"),
        schema="core",
    )
    op.create_index("ix_core_cameras_code", "cameras", ["code"], unique=True, schema="core")
    op.create_index("ix_core_cameras_site_id", "cameras", ["site_id"], schema="core")

    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["core.users.id"],
            name="fk_refresh_tokens_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_id"],
            ["core.refresh_tokens.id"],
            name="fk_refresh_tokens_replaced_by_id_refresh_tokens",
            ondelete="SET NULL",
        ),
        schema="core",
    )
    op.create_index("ix_core_refresh_tokens_user_id", "refresh_tokens", ["user_id"], schema="core")

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=True),
        sa.Column("entity_id", sa.String(length=100), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["core.users.id"],
            name="fk_audit_log_user_id_users",
            ondelete="SET NULL",
        ),
        schema="core",
    )
    op.create_index("ix_core_audit_log_user_id", "audit_log", ["user_id"], schema="core")
    op.create_index("ix_core_audit_log_action", "audit_log", ["action"], schema="core")
    op.create_index("ix_core_audit_log_created_at", "audit_log", ["created_at"], schema="core")


def downgrade() -> None:
    op.drop_table("audit_log", schema="core")
    op.drop_table("refresh_tokens", schema="core")
    op.drop_table("cameras", schema="core")
    op.drop_table("users", schema="core")  # drops the user_role type too (create_type=True)
    op.execute("DROP SCHEMA IF EXISTS core")
