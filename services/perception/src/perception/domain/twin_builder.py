"""Assembles a `TwinV1` document from already-computed per-frame detections
— pure (no I/O; ML inference happens in `adapters/`, this only shapes the
result). P2-D4.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import datetime

from vms_common.contracts.twin import (
    Frame,
    FrameObject,
    FrameSize,
    ObjectAttributes,
    Scene,
    TrackSummary,
    TwinV1,
)

VEHICLE_CATEGORIES = frozenset({"car", "motorcycle", "bus", "truck", "bicycle"})


def build_twin(
    *,
    segment_id: str,
    camera_id: str,
    site_id: str,
    start_ts: datetime,
    end_ts: datetime,
    sample_fps: float,
    frame_size: tuple[int, int],
    frames: list[Frame],
    best_crop_uris: dict[str, str],
    embedding_indices: dict[str, int],
) -> TwinV1:
    """Build the twin document. `tracks` and `scene` are derived from `frames`;
    `best_crop_uris`/`embedding_indices` must have an entry for every
    `track_id` that appears in `frames` (a missing entry is a caller bug —
    this raises `KeyError` rather than silently defaulting).
    """
    return TwinV1(
        segment_id=segment_id,
        camera_id=camera_id,
        site_id=site_id,
        start_ts=start_ts,
        end_ts=end_ts,
        sample_fps=sample_fps,
        frame_size=FrameSize(w=frame_size[0], h=frame_size[1]),
        frames=frames,
        tracks=_summarize_tracks(
            frames, best_crop_uris=best_crop_uris, embedding_indices=embedding_indices
        ),
        scene=_summarize_scene(frames),
    )


def _summarize_tracks(
    frames: list[Frame], *, best_crop_uris: dict[str, str], embedding_indices: dict[str, int]
) -> list[TrackSummary]:
    by_track: dict[str, list[tuple[Frame, FrameObject]]] = defaultdict(list)
    for frame in frames:
        for obj in frame.objects:
            by_track[obj.track_id].append((frame, obj))

    summaries = []
    for track_id, entries in by_track.items():
        entries.sort(key=lambda pair: pair[0].ts)
        first_ts = entries[0][0].ts
        last_ts = entries[-1][0].ts

        zones_visited: list[str] = []
        seen_zones: set[str] = set()
        for _frame, obj in entries:
            for zone in obj.zones:
                if zone not in seen_zones:
                    seen_zones.add(zone)
                    zones_visited.append(zone)

        summaries.append(
            TrackSummary(
                track_id=track_id,
                category=entries[-1][1].category,  # most recent classification wins
                first_ts=first_ts,
                last_ts=last_ts,
                dwell_s=max((last_ts - first_ts).total_seconds(), 0.0),
                zones_visited=zones_visited,
                attributes_summary=_most_common_attributes(obj for _frame, obj in entries),
                best_crop_uri=best_crop_uris[track_id],
                embedding_index=embedding_indices[track_id],
            )
        )
    return summaries


def _most_common_attributes(objects: Iterable[FrameObject]) -> ObjectAttributes:
    objects = list(objects)
    upper = Counter(o.attributes.upper_color for o in objects if o.attributes.upper_color)
    lower = Counter(o.attributes.lower_color for o in objects if o.attributes.lower_color)
    color = Counter(o.attributes.color for o in objects if o.attributes.color)
    return ObjectAttributes(
        upper_color=upper.most_common(1)[0][0] if upper else None,
        lower_color=lower.most_common(1)[0][0] if lower else None,
        color=color.most_common(1)[0][0] if color else None,
    )


def _summarize_scene(frames: list[Frame]) -> Scene:
    person_max = 0
    vehicle_max = 0
    for frame in frames:
        person_count = sum(1 for o in frame.objects if o.category == "person")
        vehicle_count = sum(1 for o in frame.objects if o.category in VEHICLE_CATEGORIES)
        person_max = max(person_max, person_count)
        vehicle_max = max(vehicle_max, vehicle_count)
    return Scene(person_count_max=person_max, vehicle_count_max=vehicle_max)
