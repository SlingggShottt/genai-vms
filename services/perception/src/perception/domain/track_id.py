"""Track id formatting — pure. glossary (context.md §8): `{camera_id}-t{n}`."""

from __future__ import annotations


def format_track_id(camera_id: str, track_num: int) -> str:
    """`cam03-t412` — glossary format, must stay stable across segment
    boundaries for the same physical track (P2-D2)."""
    if track_num < 0:
        raise ValueError(f"track_num must be >= 0, got {track_num}")
    return f"{camera_id}-t{track_num}"
