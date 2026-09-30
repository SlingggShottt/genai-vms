"""media + vision schemas: segments, tracks, track_segments, minute_counts

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS media")
    op.execute("CREATE SCHEMA IF NOT EXISTS vision")

    op.create_table(
        "segments",
        sa.Column("segment_id", sa.String(length=200), nullable=False),
        sa.Column("camera_id", sa.String(length=100), nullable=False),
        sa.Column("site_id", sa.String(length=100), nullable=False),
        sa.Column("start_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("twin_uri", sa.Text(), nullable=False),
        sa.Column("perception_version", sa.String(length=200), nullable=False),
        sa.Column(
            "indexed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("segment_id", name="pk_segments"),
        schema="media",
    )
    op.create_index(
        "ix_media_segments_camera_id_start_ts",
        "segments",
        ["camera_id", "start_ts"],
        schema="media",
    )

    op.create_table(
        "tracks",
        sa.Column("track_id", sa.String(length=100), nullable=False),
        sa.Column("camera_id", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("first_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "zones_visited",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("attributes_summary", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("best_crop_uri", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("track_id", name="pk_tracks"),
        schema="vision",
    )
    op.create_index("ix_vision_tracks_camera_id", "tracks", ["camera_id"], schema="vision")

    op.create_table(
        "track_segments",
        sa.Column("track_id", sa.String(length=100), nullable=False),
        sa.Column("segment_id", sa.String(length=200), nullable=False),
        sa.Column("camera_id", sa.String(length=100), nullable=False),
        sa.Column("first_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dwell_s", sa.Float(), nullable=False),
        sa.Column(
            "zones_visited",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("attributes_summary", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("best_crop_uri", sa.Text(), nullable=False),
        sa.Column("embedding_index", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("track_id", "segment_id", name="pk_track_segments"),
        sa.ForeignKeyConstraint(
            ["track_id"],
            ["vision.tracks.track_id"],
            name="fk_track_segments_track_id_tracks",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id"],
            ["media.segments.segment_id"],
            name="fk_track_segments_segment_id_segments",
            ondelete="CASCADE",
        ),
        schema="vision",
    )
    op.create_index(
        "ix_vision_track_segments_segment_id",
        "track_segments",
        ["segment_id"],
        schema="vision",
    )

    op.create_table(
        "minute_counts",
        sa.Column("camera_id", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("minute_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("site_id", sa.String(length=100), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("camera_id", "category", "minute_ts", name="pk_minute_counts"),
        schema="vision",
    )
    op.create_index(
        "ix_vision_minute_counts_camera_id_minute_ts",
        "minute_counts",
        ["camera_id", "minute_ts"],
        schema="vision",
    )


def downgrade() -> None:
    op.drop_table("minute_counts", schema="vision")
    op.drop_table("track_segments", schema="vision")
    op.drop_table("tracks", schema="vision")
    op.drop_table("segments", schema="media")
    op.execute("DROP SCHEMA IF EXISTS vision")
    op.execute("DROP SCHEMA IF EXISTS media")
