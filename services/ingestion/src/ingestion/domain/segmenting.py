"""Pure segment-naming and object-storage key layout — no I/O.

This is what unit tests target directly (style_guide.md §A.1: `domain/`
has no I/O, and is where most tests live).
"""

from __future__ import annotations

from datetime import datetime


def build_segment_id(camera_id: str, start_ts: datetime, seq: int) -> str:
    """`{camera_id}_{start_utc}_{seq}` (SRS §5), e.g. `cam03_20261005T101500Z_000123`."""
    return f"{camera_id}_{start_ts.strftime('%Y%m%dT%H%M%SZ')}_{seq:06d}"


def build_segment_key(camera_id: str, start_ts: datetime, segment_id: str) -> str:
    """`vms-segments` key layout (design_architecture.md §6.3):
    `{camera}/{yyyy}/{mm}/{dd}/{hh}/{segment_id}.ts`.
    """
    return f"{camera_id}/{start_ts:%Y}/{start_ts:%m}/{start_ts:%d}/{start_ts:%H}/{segment_id}.ts"


def build_keyframes_prefix(camera_id: str, start_ts: datetime, seq: int) -> str:
    """`vms-keyframes` key prefix: `{camera}/{yyyy}/{mm}/{dd}/{hh}/{seq:06d}/`."""
    return f"{camera_id}/{start_ts:%Y}/{start_ts:%m}/{start_ts:%d}/{start_ts:%H}/{seq:06d}/"


def build_keyframe_key(keyframes_prefix: str, index: int) -> str:
    """One keyframe's key within its prefix: `{prefix}{index:04d}.jpg`."""
    return f"{keyframes_prefix}{index:04d}.jpg"
