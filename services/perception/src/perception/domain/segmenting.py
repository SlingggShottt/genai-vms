"""Object storage key layout for perception's outputs — pure
(design_architecture.md §5.3, §6.3). `vms-twins` holds both the twin JSON
and its `.npz` embeddings, keyed by the segment's sequence number under
`{camera}/{yyyy}/{mm}/{dd}/{hh}/`, matching the worked example in §5.3:
`s3://vms-twins/cam03/2026/10/05/10/000123.json`.
"""

from __future__ import annotations

from datetime import datetime


def parse_segment_seq(segment_id: str) -> int:
    """Extract the trailing 6-digit sequence from `{camera}_{ts}_{seq}` (SRS §5)."""
    return int(segment_id.rsplit("_", 1)[-1])


def build_twin_key(camera_id: str, start_ts: datetime, segment_id: str) -> str:
    seq = parse_segment_seq(segment_id)
    return f"{camera_id}/{start_ts:%Y}/{start_ts:%m}/{start_ts:%d}/{start_ts:%H}/{seq:06d}.json"


def build_embeddings_key(camera_id: str, start_ts: datetime, segment_id: str) -> str:
    seq = parse_segment_seq(segment_id)
    return f"{camera_id}/{start_ts:%Y}/{start_ts:%m}/{start_ts:%d}/{start_ts:%H}/{seq:06d}.npz"


def build_crop_key(camera_id: str, start_ts: datetime, segment_id: str, track_id: str) -> str:
    """`vms-crops` key: one best-crop image per track (§7.2 example:
    `s3://vms-crops/.../cam03-t412.jpg`)."""
    seq = parse_segment_seq(segment_id)
    return (
        f"{camera_id}/{start_ts:%Y}/{start_ts:%m}/{start_ts:%d}/{start_ts:%H}/"
        f"{seq:06d}/{track_id}.jpg"
    )


def build_perception_keyframe_key(
    camera_id: str, start_ts: datetime, segment_id: str, frame_idx: int
) -> str:
    """`vms-keyframes` key for perception's *own* sampled frames.

    Ingestion already uploads 1 fps keyframes under
    `{camera}/.../{seq:06d}/{nnnn}.jpg` (FR-ING-04). Perception decodes and
    samples the segment independently at up to 2x that rate
    (design_architecture.md §7.1), so reusing the same numeric filenames
    under the same `{seq:06d}/` folder would silently collide with
    ingestion's files. The `p` prefix keeps perception's frames in the same
    folder without overwriting ingestion's.
    """
    seq = parse_segment_seq(segment_id)
    return (
        f"{camera_id}/{start_ts:%Y}/{start_ts:%m}/{start_ts:%d}/{start_ts:%H}/"
        f"{seq:06d}/p{frame_idx:04d}.jpg"
    )
