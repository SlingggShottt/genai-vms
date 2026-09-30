"""Qdrant payload shaping for `frames`/`tracks` points — no I/O
(design_architecture.md §6.2).

One point per `twin.frames[i]` and one per `twin.tracks[i]` — the latter is
a track's best crop *for this segment*, not one point merged across every
segment a track appears in (that would need a payload read-merge-write on
`segment_ids[]`/the embedding vector on every new segment, which this
smoke-test-scale story doesn't need — see `indexer/README.md`). So
`segment_ids` here always holds exactly this one segment; a track spanning
several segments gets several points, one per segment, which retrieval can
merge by `track_id` if it wants a single hit later.
"""

from __future__ import annotations

from datetime import datetime

from vms_common.contracts.twin import Frame, TrackSummary


def build_frame_payload(
    frame: Frame, *, camera_id: str, site_id: str, segment_id: str
) -> dict[str, object]:
    categories = sorted({obj.category for obj in frame.objects})
    person_count = sum(1 for obj in frame.objects if obj.category == "person")
    return {
        "camera_id": camera_id,
        "site_id": site_id,
        "ts": _epoch_ms(frame.ts),
        "segment_id": segment_id,
        "keyframe_uri": frame.keyframe_uri,
        "categories": categories,
        "person_count": person_count,
    }


def build_track_payload(
    track: TrackSummary, *, camera_id: str, segment_id: str
) -> dict[str, object]:
    return {
        "track_id": track.track_id,
        "camera_id": camera_id,
        "category": track.category,
        "colors": _colors(track),
        "first_ts": _epoch_ms(track.first_ts),
        "last_ts": _epoch_ms(track.last_ts),
        "zones": track.zones_visited,
        "crop_uri": track.best_crop_uri,
        "segment_ids": [segment_id],
    }


def _colors(track: TrackSummary) -> list[str]:
    attrs = track.attributes_summary
    return sorted({c for c in (attrs.upper_color, attrs.lower_color, attrs.color) if c})


def _epoch_ms(ts: datetime) -> int:
    return int(ts.timestamp() * 1000)
