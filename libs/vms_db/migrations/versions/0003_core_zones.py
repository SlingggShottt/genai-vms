"""core schema: zones

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ZONE_TYPE_ENUM = postgresql.ENUM(
    "generic", "restricted", "entrance", "exit", name="zone_type", schema="core"
)


def upgrade() -> None:
    op.create_table(
        "zones",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("zone_type", ZONE_TYPE_ENUM, nullable=False),
        sa.Column("polygon", postgresql.JSONB(), nullable=False),
        sa.Column("schedule", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_zones"),
        sa.ForeignKeyConstraint(
            ["camera_id"],
            ["core.cameras.id"],
            name="fk_zones_camera_id_cameras",
            ondelete="CASCADE",
        ),
        schema="core",
    )
    op.create_index("ix_core_zones_camera_id", "zones", ["camera_id"], schema="core")


def downgrade() -> None:
    op.drop_table("zones", schema="core")  # drops the zone_type type too (create_type=True)
