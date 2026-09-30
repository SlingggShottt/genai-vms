"""Fetches twin documents from object storage for the overlay endpoint
(P2-J3). Bboxes/track-ids live only in the twin JSON in S3, not in
Postgres — `vision.track_segments` only has per-track *summaries*.
"""

from __future__ import annotations

from datetime import datetime

from vms_common.contracts.twin import Frame, TwinV1
from vms_common.storage.s3 import S3Client
from vms_db.models import Segment

from api.domain.recordings import frames_in_range


async def frames_for_segments(
    s3: S3Client, segments: list[Segment], *, start: datetime, end: datetime
) -> list[Frame]:
    """Fetch each segment's twin document and collect the frames within
    `[start, end]`, across however many segments the window spans.
    """
    frames: list[Frame] = []
    for segment in segments:
        twin_bytes = await s3.get_bytes(segment.twin_uri)
        twin = TwinV1.model_validate_json(twin_bytes)
        frames.extend(frames_in_range(twin, start=start, end=end))
    frames.sort(key=lambda f: f.ts)
    return frames
