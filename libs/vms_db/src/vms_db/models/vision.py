"""ORM models for the `vision` schema — track summaries and per-minute
density (design_architecture.md §6.1). Owner: J. Written by the indexer
service (P2-J1) from `twinready.v1`'s twin document.

`Track` is the cross-segment view of a track (ByteTrack ids continue across
segment boundaries — design §7.1); `TrackSegment` is the per-segment
summary the perception twin actually carries. `Track` rows are always
recomputed from their `TrackSegment` rows (see `indexer.adapters.repository`)
rather than merged incrementally, so re-indexing is naturally idempotent and
order-independent.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from vms_common.types import CameraCode

from vms_db.base import Base

SCHEMA = "vision"


class Track(Base):
    """`vision.tracks` — one row per globally unique `track_id`, aggregated
    across every segment it appears in.
    """

    __tablename__ = "tracks"
    __table_args__ = (
        Index("ix_vision_tracks_camera_id", "camera_id"),
        {"schema": SCHEMA},
    )

    track_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    camera_id: Mapped[CameraCode] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    first_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    zones_visited: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    attributes_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    best_crop_uri: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TrackSegment(Base):
    """`vision.track_segments` — the segment-local `TrackSummary` from one
    segment's twin document (twin.v1 §7.2), keyed so replaying the same
    `twinready.v1` message is a no-op overwrite, not a duplicate row.
    """

    __tablename__ = "track_segments"
    __table_args__ = (
        Index("ix_vision_track_segments_segment_id", "segment_id"),
        {"schema": SCHEMA},
    )

    track_id: Mapped[str] = mapped_column(
        String(100), ForeignKey(f"{SCHEMA}.tracks.track_id", ondelete="CASCADE"), primary_key=True
    )
    segment_id: Mapped[str] = mapped_column(
        String(200), ForeignKey("media.segments.segment_id", ondelete="CASCADE"), primary_key=True
    )
    camera_id: Mapped[CameraCode] = mapped_column(String(100), nullable=False)
    first_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dwell_s: Mapped[float] = mapped_column(Float, nullable=False)
    zones_visited: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    attributes_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    best_crop_uri: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_index: Mapped[int] = mapped_column(Integer, nullable=False)


class MinuteCount(Base):
    """`vision.minute_counts` — max simultaneous object count per
    camera/category/minute, the source for density sparklines (P2-J3) and
    the assistant's `count_objects` tool (design_architecture.md §10.3).

    Upserted with `GREATEST(existing, new)` per minute (see
    `indexer.adapters.repository`): idempotent under replay of the *same*
    segment (its contribution is deterministic), and a reasonable
    approximation — not an exact simultaneous max — for a minute that spans
    several segments, since each segment only sees its own ~10s window.
    """

    __tablename__ = "minute_counts"
    __table_args__ = (
        Index("ix_vision_minute_counts_camera_id_minute_ts", "camera_id", "minute_ts"),
        {"schema": SCHEMA},
    )

    camera_id: Mapped[CameraCode] = mapped_column(String(100), primary_key=True)
    category: Mapped[str] = mapped_column(String(50), primary_key=True)
    minute_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    site_id: Mapped[str] = mapped_column(String(100), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
