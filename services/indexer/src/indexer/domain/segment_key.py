"""Segment object-storage key layout — no I/O.

`twinready.v1` doesn't carry the segment video's own `s3://` URI (only the
twin and embeddings URIs — CLAUDE.md: no cross-service payload duplication
beyond what's on the contract). The key layout itself is a frozen,
documented convention (design_architecture.md §6.3), so the indexer
re-derives it here rather than importing ingestion's copy (services never
import other services — CLAUDE.md hard rule). Keep this in sync with
`services/ingestion/src/ingestion/domain/segmenting.py::build_segment_key`
if that layout ever changes (which needs a contract-freeze discussion
first, per the hard rule on cross-service payloads).
"""

from __future__ import annotations

from datetime import datetime


def build_segment_uri(camera_id: str, start_ts: datetime, segment_id: str) -> str:
    """`s3://vms-segments/{camera}/{yyyy}/{mm}/{dd}/{hh}/{segment_id}.ts`."""
    key = f"{camera_id}/{start_ts:%Y}/{start_ts:%m}/{start_ts:%d}/{start_ts:%H}/{segment_id}.ts"
    return f"s3://vms-segments/{key}"
