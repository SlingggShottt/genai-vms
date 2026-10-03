"""core schema: topology_edges

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EDGE_TYPE_ENUM = postgresql.ENUM("overlap", "transit", name="edge_type", schema="core")


def upgrade() -> None:
    op.create_table(
        "topology_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_camera_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_camera_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("edge_type", EDGE_TYPE_ENUM, nullable=False),
        sa.Column("min_s", sa.Float(), nullable=True),
        sa.Column("max_s", sa.Float(), nullable=True),
        sa.Column("tolerance_s", sa.Float(), nullable=True),
        sa.Column("bidirectional", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_topology_edges")),
        sa.ForeignKeyConstraint(
            ["from_camera_id"],
            ["core.cameras.id"],
            name=op.f("fk_topology_edges_from_camera_id_cameras"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["to_camera_id"],
            ["core.cameras.id"],
            name=op.f("fk_topology_edges_to_camera_id_cameras"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "from_camera_id <> to_camera_id", name=op.f("ck_topology_edges_distinct_cameras")
        ),
        sa.CheckConstraint(
            "(edge_type = 'overlap' AND tolerance_s IS NOT NULL AND tolerance_s >= 0"
            " AND min_s IS NULL AND max_s IS NULL AND bidirectional)"
            " OR (edge_type = 'transit' AND tolerance_s IS NULL"
            " AND min_s IS NOT NULL AND max_s IS NOT NULL AND min_s >= 0 AND max_s >= min_s)",
            name=op.f("ck_topology_edges_edge_parameters"),
        ),
        sa.UniqueConstraint(
            "from_camera_id",
            "to_camera_id",
            "edge_type",
            name=op.f("uq_topology_edges_pair"),
        ),
        schema="core",
    )
    op.create_index(
        "ix_core_topology_edges_from_camera_id", "topology_edges", ["from_camera_id"], schema="core"
    )
    op.create_index(
        "ix_core_topology_edges_to_camera_id", "topology_edges", ["to_camera_id"], schema="core"
    )
    # Overlap is symmetric, so A->B and B->A are the same edge: one row per unordered pair.
    op.create_index(
        "uq_topology_edges_overlap_pair",
        "topology_edges",
        [
            sa.text("LEAST(from_camera_id, to_camera_id)"),
            sa.text("GREATEST(from_camera_id, to_camera_id)"),
        ],
        unique=True,
        schema="core",
        postgresql_where=sa.text("edge_type = 'overlap'"),
    )


def downgrade() -> None:
    op.drop_table("topology_edges", schema="core")
    # drop_table does not drop the Postgres enum type it created: without this a
    # downgrade-then-upgrade fails with "type edge_type already exists".
    op.execute("DROP TYPE core.edge_type")
