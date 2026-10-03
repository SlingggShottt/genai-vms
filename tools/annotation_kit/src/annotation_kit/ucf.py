"""UCF-Crime incidents as phase-annotation candidates.

UCF-Crime (Sultani, Chen, Shah, CVPR 2018) is untrimmed, single-view surveillance video in 13
anomaly classes; a class is the folder its videos sit in. This is the source for single-view
incidents with a clear before, during and after.

NOT VERIFIED AGAINST THE REAL FILES. The dataset host (www.crcv.ucf.edu) was not reachable when this
was written, so the reader follows the convention the dataset publishes, as remembered and as
documented in the repo's dataset notes, and has only been run on fixtures in that shape. The one
file that matters is `Temporal_Anomaly_Annotation_for_Testing_Videos.txt`, one video per line:

    Abuse028_x264.mp4  Abuse  165  240  -1  -1

the file name, the class, then one or two frame spans (30 fps) where the anomaly happens, -1 for
"no second span". Only the test videos have spans; a training video is an untrimmed clip with an
anomaly somewhere in it, so it is offered whole (up to a length cap) and the annotators find it.
Run it on the first real download and read `annotation-kit ucf-candidates`' summary before
trusting it.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from annotation_kit.candidates import PhaseCandidate, ViewSpec

FPS = 30
# The eight with a clear approach, build-up, act and response, and a place in this project (the
# violent and theft incidents the event rules and the incident reports are about). The rest of the
# thirteen (arson, explosion, road accidents, shooting, stealing) either have no scene to phase
# (an explosion has no approach) or are covered by a class kept here.
DEFAULT_CLASSES: tuple[str, ...] = (
    "Abuse",
    "Arrest",
    "Assault",
    "Burglary",
    "Fighting",
    "Robbery",
    "Shoplifting",
    "Vandalism",
)
CAMERA = "cam01"  # single view
_VIDEO_NAME = re.compile(r"^(?P<cls>[A-Za-z]+?)(?P<num>\d+)(?:_x264)?\.(?:mp4|avi)$")


@dataclass(frozen=True)
class UcfConfig:
    classes: tuple[str, ...] = DEFAULT_CLASSES
    pad_before_s: float = 10.0
    pad_after_s: float = 10.0
    max_window_s: float = 90.0
    per_class_cap: int | None = 40
    seed: int = 0
    uri_prefix: str = (
        ""  # prepended to a video's path under the dataset root, e.g. "s3://bucket/ucf/"
    )


@dataclass(frozen=True)
class Span:
    start_s: float
    end_s: float


def read_temporal_annotations(path: str | Path) -> dict[str, tuple[str, list[Span]]]:
    """`{video file: (class, [anomaly spans])}` from the testing videos' annotation file."""
    out: dict[str, tuple[str, list[Span]]] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            fields = line.split()
            if len(fields) < 4:
                continue
            video, cls = fields[0], fields[1]
            numbers = []
            for token in fields[2:6]:
                try:
                    numbers.append(int(token))
                except ValueError:
                    numbers.append(-1)
            spans = [
                Span(a / FPS, b / FPS)
                for a, b in zip(numbers[0::2], numbers[1::2], strict=False)
                if a >= 0 and b > a
            ]
            out[video] = (cls, spans)
    return out


@dataclass(frozen=True)
class UcfVideo:
    name: str  # the file name, "Abuse028_x264.mp4"
    cls: str
    path: str  # where it is, relative to the dataset root
    duration_s: float | None = None


def scan_videos(root: str | Path, classes: Sequence[str]) -> list[UcfVideo]:
    """Videos under `root` whose parent folder is one of `classes` (case-insensitive)."""
    wanted = {c.casefold(): c for c in classes}
    base = Path(root)
    found: list[UcfVideo] = []
    for path in sorted(base.rglob("*")):
        if path.suffix.lower() not in (".mp4", ".avi") or path.parent.name.casefold() not in wanted:
            continue
        found.append(
            UcfVideo(
                path.name, wanted[path.parent.name.casefold()], path.relative_to(base).as_posix()
            )
        )
    return found


def probe_duration(path: str | Path) -> float | None:
    """A video's length in seconds via ffprobe; None if it cannot be read or ffprobe is missing."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - the tool's own full path, a fixed set of flags
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return float(result.stdout.strip()) if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


@dataclass
class UcfSelection:
    candidates: list[PhaseCandidate] = field(default_factory=list)
    skipped: Counter[str] = field(default_factory=Counter)
    seen: Counter[str] = field(default_factory=Counter)  # videos, by class

    def by_class(self) -> Counter[str]:
        return Counter(c.activity or "" for c in self.candidates)


def select_candidates(
    videos: Iterable[UcfVideo],
    annotations: Mapping[str, tuple[str, list[Span]]],
    config: UcfConfig | None = None,
) -> UcfSelection:
    """One candidate per video: around its anomaly span if it has one, else its opening stretch."""
    config = config or UcfConfig()
    out = UcfSelection()
    for video in videos:
        out.seen[video.cls] += 1
        _cls, spans = annotations.get(video.name, (video.cls, []))
        if spans:
            start = max(0.0, min(s.start_s for s in spans) - config.pad_before_s)
            end = max(s.end_s for s in spans) + config.pad_after_s
            if end - start > config.max_window_s:
                # a very long anomaly: keep its start, which is where the lead-up is
                end = start + config.max_window_s
                out.skipped["window_shortened"] += 1
        else:
            start, end = 0.0, config.max_window_s
        if video.duration_s is not None:
            end = min(end, video.duration_s)
        if end - start < 1.0:
            out.skipped["too_short"] += 1
            continue
        stem = video.name.rsplit(".", 1)[0]
        out.candidates.append(
            PhaseCandidate(
                candidate_id=f"ucf_crime:{stem}",
                dataset="ucf_crime",
                source_video=f"ucf_crime:{stem}",
                event_type=video.cls.casefold(),
                activity=video.cls,
                primary_view=CAMERA,
                views=[
                    ViewSpec(
                        camera=CAMERA,
                        source_uri=config.uri_prefix + video.path,
                        start_s=start,
                        end_s=end,
                    )
                ],
                note="around the annotated anomaly" if spans else "untrimmed: anomaly not located",
            )
        )
    out.candidates = _cap(out.candidates, config)
    out.candidates.sort(key=lambda c: c.candidate_id)
    return out


def _cap(candidates: list[PhaseCandidate], config: UcfConfig) -> list[PhaseCandidate]:
    if config.per_class_cap is None:
        return candidates
    groups: dict[str, list[PhaseCandidate]] = defaultdict(list)
    for candidate in candidates:
        groups[candidate.activity or ""].append(candidate)
    kept: list[PhaseCandidate] = []
    for group in groups.values():
        group.sort(
            key=lambda c: hashlib.sha256(f"{config.seed}:{c.candidate_id}".encode()).hexdigest()
        )
        kept.extend(group[: config.per_class_cap])
    return kept


def summarise(selection: UcfSelection) -> str:
    lines = ["| Class | Videos | Candidates |", "|---|---:|---:|"]
    chosen = selection.by_class()
    for cls in sorted(selection.seen):
        lines.append(f"| {cls} | {selection.seen[cls]} | {chosen.get(cls, 0)} |")
    lines.append(f"| **all** | {sum(selection.seen.values())} | {len(selection.candidates)} |")
    if selection.skipped:
        lines += [
            "",
            "Noted: " + ", ".join(f"{n} {why}" for why, n in selection.skipped.most_common()),
        ]
    return "\n".join(lines) + "\n"
