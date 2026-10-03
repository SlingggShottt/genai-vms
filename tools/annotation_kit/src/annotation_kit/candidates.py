"""Candidate incident clips for phase annotation, whichever dataset they come from.

A candidate is one stretch of time seen by one or more cameras. For every view it says which source
video to cut from and where, in *that video's own time*, so that cutting all views gives clips of
the same length that show the same moment. Phases are then marked once, in seconds from the start
of the clip, and apply to every view: that only holds if the views were cut in sync, which is why
the cut points are computed here and not left to whoever runs ffmpeg.

`source_video` is what train/validation/test are split by (design section 8.3). It is the unit that
must not straddle a split: for MEVA every candidate in the same camera set and five-minute slot
shares one, because two incidents a minute apart on the same cameras are near-duplicates.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

FPS = 30  # clips are cut at a constant 30 fps, so Label Studio's frame numbers are unambiguous
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ViewSpec(_Strict):
    camera: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)  # the whole source video this view is cut from
    start_s: float = Field(ge=0)  # the window, in this source video's own time
    end_s: float

    @model_validator(mode="after")
    def _ends_after_it_starts(self) -> Self:
        if self.end_s <= self.start_s:
            raise ValueError(f"{self.camera}: end_s must be after start_s")
        return self

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


class PhaseCandidate(_Strict):
    schema_version: Literal["phase_candidate.v1"] = "phase_candidate.v1"
    candidate_id: str = Field(min_length=1)
    dataset: Literal["meva", "ucf_crime"]
    source_video: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    activity: str | None = None  # the dataset's own label for what happens
    primary_view: str
    views: list[ViewSpec] = Field(min_length=1)
    note: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        cameras = [view.camera for view in self.views]
        if len(set(cameras)) != len(cameras):
            raise ValueError(f"{self.candidate_id}: a camera appears twice")
        if self.primary_view not in cameras:
            raise ValueError(f"{self.candidate_id}: primary_view is not one of the views")
        lengths = [view.duration_s for view in self.views]
        if max(lengths) - min(lengths) > 0.05:
            raise ValueError(
                f"{self.candidate_id}: views must be cut to the same length, got {lengths}"
            )
        return self

    @property
    def duration_s(self) -> float:
        return self.views[0].duration_s


def safe_id(candidate_id: str) -> str:
    """The candidate's id as a folder name."""
    return _UNSAFE.sub("_", candidate_id).strip("_")


def clip_relpath(candidate: PhaseCandidate, view: ViewSpec) -> str:
    """Where a cut view lives, relative to the clips folder or bucket prefix."""
    return f"{safe_id(candidate.candidate_id)}/{view.camera}.mp4"


def clip_uri(prefix: str, candidate: PhaseCandidate, view: ViewSpec) -> str:
    return f"{prefix.rstrip('/')}/{clip_relpath(candidate, view)}"


def cut_command(
    view: ViewSpec,
    out_path: str | Path,
    *,
    resolve_source=None,  # type: ignore[no-untyped-def]
) -> list[str]:
    """The ffmpeg argv that cuts one view: re-encoded, so the start is frame-accurate, at a constant
    30 fps with a keyframe every second so the labelling player can seek.
    """
    source = resolve_source(view.source_uri) if resolve_source else view.source_uri
    return [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-ss",
        f"{view.start_s:.3f}",
        "-i",
        source,
        "-t",
        f"{view.duration_s:.3f}",
        "-an",
        "-r",
        str(FPS),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-g",
        str(FPS),
        "-pix_fmt",
        "yuv420p",
        str(out_path),
    ]
