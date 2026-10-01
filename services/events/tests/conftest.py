"""Shared builders for the events unit tests: zones, objects and synthetic
twin *sequences* (the rules are temporal, so most tests need many segments).

Exposed as the `make` fixture: `make.zone(...)`, `make.obj(...)`,
`make.frames(...)`, `make.twins(...)`, `make.run(...)`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from events.domain.candidates import CandidateUpdate
from events.domain.config import RulesConfig
from events.domain.engine import process_twin
from events.domain.state import CameraState
from vms_common.contracts.twin import Frame, FrameObject, FrameSize, TwinV1
from vms_common.contracts.zones import ZoneInternal, ZoneSchedule

# 2026-10-01 07:00:00 UTC == 12:30 IST, a Thursday.
T0 = datetime(2026, 10, 1, 7, 0, 0, tzinfo=UTC)
IST = ZoneInfo("Asia/Kolkata")
SEGMENT_S = 10.0
FPS = 2.0

FrameSpec = tuple[float, list[FrameObject]]  # (seconds from the sequence start, objects)


def zone(
    name: str = "yard",
    zone_type: str = "restricted",
    *,
    camera_id: str = "cam01",
    schedule: ZoneSchedule | None = None,
    zone_id: str | None = None,
) -> ZoneInternal:
    return ZoneInternal(
        id=zone_id or f"zone-{name}",
        camera_id=camera_id,
        name=name,
        zone_type=zone_type,  # type: ignore[arg-type]
        polygon=[(0.1, 0.1), (0.9, 0.1), (0.9, 0.9)],
        schedule=schedule,
    )


def obj(
    track_id: str = "cam01-t1",
    category: str = "person",
    *,
    zones: Sequence[str] = ("yard",),
    conf: float = 0.9,
) -> FrameObject:
    return FrameObject(
        track_id=track_id,
        category=category,
        conf=conf,
        bbox=(0.4, 0.4, 0.5, 0.8),
        zones=list(zones),
    )


def frames(
    seconds: float,
    objects: Sequence[FrameObject],
    *,
    start: float = 0.0,
    fps: float = FPS,
) -> list[FrameSpec]:
    """`objects` present in every sample from `start` to `start + seconds`, both
    ends included — so `frames(60, ...)` spans exactly 60 s first-to-last."""
    count = round(seconds * fps) + 1
    return [(start + i / fps, list(objects)) for i in range(count)]


def twins(
    specs: Sequence[FrameSpec],
    *,
    camera_id: str = "cam01",
    start: datetime = T0,
    total_s: float | None = None,
    segment_s: float = SEGMENT_S,
) -> list[TwinV1]:
    """Cut frame specs into consecutive `segment_s` twins starting at `start`.
    Segments with no frames are still produced (a quiet segment is a twin with
    no detections), up to `total_s` if given."""
    if not specs and total_s is None:
        return []
    last_offset = max([o for o, _ in specs], default=0.0)
    horizon = max(last_offset, (total_s or 0.0) - 1e-9)
    count = int(horizon // segment_s) + 1
    by_segment: dict[int, list[FrameSpec]] = {i: [] for i in range(count)}
    for offset, objects in specs:
        by_segment[int(offset // segment_s)].append((offset, objects))

    result: list[TwinV1] = []
    for index in range(count):
        seg_start = start + timedelta(seconds=index * segment_s)
        seg_end = seg_start + timedelta(seconds=segment_s)
        result.append(
            TwinV1(
                segment_id=f"{camera_id}_{seg_start:%Y%m%dT%H%M%SZ}_{index:06d}",
                camera_id=camera_id,
                site_id="rvce-campus",
                start_ts=seg_start,
                end_ts=seg_end,
                sample_fps=FPS,
                frame_size=FrameSize(w=1920, h=1080),
                frames=[
                    Frame(
                        ts=start + timedelta(seconds=offset),
                        idx=i,
                        keyframe_uri=f"s3://vms-keyframes/{camera_id}/{index:06d}/{i:04d}.jpg",
                        objects=objects,
                    )
                    for i, (offset, objects) in enumerate(by_segment[index])
                ],
            )
        )
    return result


@dataclass
class RunResult:
    state: CameraState
    per_twin: list[list[CandidateUpdate]] = field(default_factory=list)

    @property
    def updates(self) -> list[CandidateUpdate]:
        return [u for batch in self.per_twin for u in batch]

    def latest(self) -> dict[str, CandidateUpdate]:
        """Last update per candidate id — what the database ends up holding."""
        return {str(u.id): u for u in self.updates}


def run(
    sequence: Sequence[TwinV1],
    zones: Sequence[ZoneInternal],
    *,
    config: RulesConfig | None = None,
    state: CameraState | None = None,
    camera_id: str = "cam01",
) -> RunResult:
    state = state or CameraState(camera_id=camera_id)
    config = config or RulesConfig()
    result = RunResult(state=state)
    for twin in sequence:
        outcome = process_twin(result.state, twin, zones=zones, config=config, site_tz=IST)
        result.state = outcome.state
        result.per_twin.append(outcome.updates)
    return result


@pytest.fixture
def make() -> SimpleNamespace:
    return SimpleNamespace(
        zone=zone, obj=obj, frames=frames, twins=twins, run=run, T0=T0, IST=IST, FPS=FPS
    )
