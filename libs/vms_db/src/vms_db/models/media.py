"""ORM models for the `media` schema — recorded segment index
(design_architecture.md §6.1). Owner: J. Written by the indexer service
(P2-J1) from `twinready.v1`; read by the recordings API (P2-J3).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from vms_common.types import CameraCode

from vms_db.base import Base

SCHEMA = "media"


class Segment(Base):
    """`media.segments` — one row per recorded segment once its digital twin
    has been indexed. `uri` is the segment video's `s3://` location, derived
    from the same deterministic key layout ingestion uses
    (design_architecture.md §6.3) rather than carried on `twinready.v1`.
    """

    __tablename__ = "segments"
    __table_args__ = (
        Index("ix_media_segments_camera_id_start_ts", "camera_id", "start_ts"),
        {"schema": SCHEMA},
    )

    segment_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    camera_id: Mapped[CameraCode] = mapped_column(String(100), nullable=False)
    site_id: Mapped[str] = mapped_column(String(100), nullable=False)
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    twin_uri: Mapped[str] = mapped_column(Text, nullable=False)
    perception_version: Mapped[str] = mapped_column(String(200), nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
