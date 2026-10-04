"""MEVA multi-view activity episodes as phase-annotation candidates.

MEVA (Kitware, NIST) is a few thousand five-minute clips from cameras at one site with overlapping
fields of view, annotated with 37 *everyday* activities (people talking, entering a building, a
vehicle dropping someone off). It is not an incident dataset: in the released annotations,
abandoned packages appear in 1 clip and thefts in 4, and there is no intrusion, loitering, crowding
or running at all. What it does have, and nothing else here has, is time-synchronised views of the
same moment, so it is the source for *multi-view* phase annotation, with the activity as the
episode and whatever is the nearest event type as its label. Which activities count is
configuration (`MevaConfig`), not an assumption.

Formats, as published in the annotation repo (https://gitlab.kitware.com/meva/meva-data-repo):

- `metadata/meva-clip-camera-and-time-table.txt`: one line per clip with seven fields. Clips of one
  camera *set* (cameras sharing a field of view) in one reference time slot are frame-synchronised
  to a reference clip: frame f of a clip is frame f + offset of the reference clip, accurate to
  +/- N frames, N = -1 meaning no offset is available.
- `annotation/**/<clip>.activities.yml`: Kitware Packet Format, one `act` per activity instance
  with its name (`act2` or `act3`), a frame span (`tsr0`, 30 fps) and the actors.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from annotation_kit.candidates import PhaseCandidate, ViewSpec

FPS = 30
# The C loader is about ten times faster, and there are thousands of files; it is a safe loader too.
_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
ANNOTATION_STATUS_EXCLUDED = frozenset({"not_good", "unaudited"})

_CLIP = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})\.(?P<h1>\d{2})-(?P<m1>\d{2})-(?P<s1>\d{2})"
    r"\.(?P<h2>\d{2})-(?P<m2>\d{2})-(?P<s2>\d{2})\.(?P<site>[a-z]+)\.(?P<camera>G\d+)$"
)

# What each activity is called as an event type. The deployed event types (and the questions the
# bank asks for them) exist for the two that MEVA has, however rarely; everything else is an
# `activity`, which the bank answers with its `default` questions.
DEFAULT_EVENT_TYPES: dict[str, str] = {
    "person_abandons_package": "abandoned_object",
    "person_steals_object": "theft",
}
DEFAULT_EVENT_TYPE = "activity"

# Activities that have a beginning, a middle and an end long enough to put phases on: a vehicle
# arriving and someone getting out, two people meeting, an object changing hands. The rare incident
# activities are included whenever they exist, however few. Short, constant activities (picking an
# object up lasts 0.6 s) and the most common one (talking) are left out by default.
DEFAULT_ACTIVITIES: tuple[str, ...] = (
    "person_abandons_package",
    "person_steals_object",
    "vehicle_drops_off_person",
    "vehicle_picks_up_person",
    "person_transfers_object",
    "person_embraces_person",
    "person_loads_vehicle",
    "person_unloads_vehicle",
    "person_carries_heavy_object",
    "person_rides_bicycle",
)


@dataclass(frozen=True)
class MevaConfig:
    activities: tuple[str, ...] = DEFAULT_ACTIVITIES
    event_types: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_EVENT_TYPES))
    pad_before_s: float = 10.0  # room for a baseline before the activity
    pad_after_s: float = 10.0  # and an aftermath after it
    min_views: int = 2
    min_activity_s: float = 1.0
    max_window_s: float = 90.0
    # Near-duplicates are the risk: 2,131 candidates come from only 221 five-minute slots. These
    # defaults keep 361 from 179 slots, all eight activities present, on the released annotations.
    per_activity_cap: int | None = 60  # keep at most this many of each activity
    per_slot_cap: int | None = 3  # and at most this many from one camera set and 5-minute slot
    seed: int = 0  # which ones, when capped: deterministic
    excluded_status: frozenset[str] = ANNOTATION_STATUS_EXCLUDED
    s3_prefix: str = "s3://mevadata-public-01/drops-123-r13"


# ---- the clip table ----------------------------------------------------------------------------


@dataclass(frozen=True)
class ClipInfo:
    name: str
    slot: str  # the normalised five-minute slot, "2018-03-05.09-45-00"
    camera_set: str  # "3-420" (March, reference camera G420), "IR" or "skip"
    reference: str | None  # the clip it is synchronised to; itself for a reference clip
    offset: int  # frame f here == frame f + offset in the reference clip
    precision: int  # +/- frames; -1: no offset available
    date: str
    start_s: int  # wall clock, seconds into the day
    end_s: int
    site: str
    camera: str

    @property
    def frames(self) -> int:
        return (self.end_s - self.start_s) * FPS

    @property
    def synchronised(self) -> bool:
        return (
            self.camera_set not in ("IR", "skip")
            and self.precision != -1
            and self.reference is not None
        )

    @property
    def group(self) -> tuple[str, str]:
        """Clips with the same group show the same moment through different cameras."""
        if self.reference is None:
            raise ValueError(f"{self.name} has no reference clip, so it is in no group")
        return (self.camera_set, self.reference)


def parse_clip_name(name: str) -> dict[str, Any] | None:
    match = _CLIP.match(name)
    if match is None:
        return None
    g = match.groupdict()
    start = int(g["h1"]) * 3600 + int(g["m1"]) * 60 + int(g["s1"])
    end = int(g["h2"]) * 3600 + int(g["m2"]) * 60 + int(g["s2"])
    if end < start:  # a clip that runs past midnight
        end += 86400
    return {
        "date": g["date"],
        "start_s": start,
        "end_s": end,
        "site": g["site"],
        "camera": g["camera"],
    }


def read_clip_table(path: str | Path) -> dict[str, ClipInfo]:
    table: dict[str, ClipInfo] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            fields = line.split()
            if len(fields) != 7:
                continue
            name, slot, _camera_file, camera_set, reference, offset, precision = fields
            parsed = parse_clip_name(name)
            if parsed is None:
                continue
            table[name] = ClipInfo(
                name=name,
                slot=slot,
                camera_set=camera_set,
                reference=None
                if reference.startswith("no-reference")
                else (name if reference == "self" else reference),
                offset=int(offset),
                precision=int(precision),
                **parsed,
            )
    return table


def sync_groups(table: Mapping[str, ClipInfo]) -> dict[tuple[str, str], list[ClipInfo]]:
    groups: dict[tuple[str, str], list[ClipInfo]] = defaultdict(list)
    for clip in table.values():
        if clip.synchronised:
            groups[clip.group].append(clip)
    return dict(groups)


# ---- the activity files ------------------------------------------------------------------------


@dataclass(frozen=True)
class Activity:
    name: str
    activity_id: int
    start_frame: int
    end_frame: int
    status: str
    actors: int


def read_activities(path: str | Path) -> list[Activity]:
    """Every activity instance in one clip's `.activities.yml` (either `act2` or `act3` style)."""
    with open(path, encoding="utf-8") as handle:
        data = yaml.load(handle, Loader=_YAML_LOADER)  # noqa: S506 - the C SafeLoader, when built
    found: list[Activity] = []
    for item in data or []:
        act = (item or {}).get("act") if isinstance(item, dict) else None
        if not isinstance(act, dict):
            continue
        names = next(
            (v for k, v in act.items() if re.fullmatch(r"act\d", str(k)) and isinstance(v, dict)),
            None,
        )
        spans = [
            span["tsr0"]
            for entry in act.get("timespan") or []
            for span in [entry]
            if isinstance(span, dict) and "tsr0" in span
        ]
        if not names or not spans:
            continue
        found.append(
            Activity(
                name=max(names, key=names.get),
                activity_id=int(act.get("id2", -1)),
                start_frame=min(int(s[0]) for s in spans),
                end_frame=max(int(s[1]) for s in spans),
                status=str(act.get("src_status") or act.get("src") or "unknown"),
                actors=len(act.get("actors") or []),
            )
        )
    return found


# ---- selecting episodes ------------------------------------------------------------------------


@dataclass
class Selection:
    candidates: list[PhaseCandidate] = field(default_factory=list)
    skipped: Counter[str] = field(default_factory=Counter)
    seen: Counter[str] = field(default_factory=Counter)  # activity instances of interest, by name

    def by_activity(self) -> Counter[str]:
        return Counter(c.activity or "" for c in self.candidates)


@dataclass
class _Episode:
    clip: ClipInfo
    activity: Activity
    window_ref: tuple[int, int]  # the padded window, in reference-clip frames
    event_ref: tuple[int, int]  # the activity itself, in reference-clip frames


def _s3_key(clip: ClipInfo, prefix: str) -> str:
    # Clips are filed by the hour they end in: 09-55-00.10-00-00 lives under .../10/.
    hour = (clip.end_s // 3600) % 24
    return f"{prefix.rstrip('/')}/{clip.date}/{hour:02d}/{clip.name}.r13.avi"


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> float:
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union else 0.0


def select_candidates(
    activities: Mapping[str, Sequence[Activity]],
    table: Mapping[str, ClipInfo],
    config: MevaConfig | None = None,
) -> Selection:
    """Turn annotated activities into multi-view candidates.

    The same real-world activity is annotated separately in every clip that sees it, so instances
    that overlap in reference time are merged into one candidate. Its primary view is the one where
    the annotators marked the most people involved.
    """
    config = config or MevaConfig()
    out = Selection()
    groups = sync_groups(table)
    wanted = set(config.activities)
    pad_before, pad_after = round(config.pad_before_s * FPS), round(config.pad_after_s * FPS)

    episodes: list[_Episode] = []
    for clip_name, instances in activities.items():
        clip = table.get(clip_name)
        for activity in instances:
            if activity.name not in wanted:
                continue
            out.seen[activity.name] += 1
            if clip is None:
                out.skipped["clip_not_in_table"] += 1
            elif activity.status in config.excluded_status:
                out.skipped["annotation_not_good"] += 1
            elif (activity.end_frame - activity.start_frame) / FPS < config.min_activity_s:
                out.skipped["activity_too_short"] += 1
            elif not clip.synchronised:
                out.skipped["not_synchronised"] += 1
            elif (
                activity.end_frame - activity.start_frame + pad_before + pad_after
            ) / FPS > config.max_window_s:
                out.skipped["window_too_long"] += 1
            else:
                event = (activity.start_frame + clip.offset, activity.end_frame + clip.offset)
                episodes.append(
                    _Episode(clip, activity, (event[0] - pad_before, event[1] + pad_after), event)
                )

    # one episode per real-world activity: merge what overlaps within a group and an activity name
    merged: list[_Episode] = []
    by_key: dict[tuple[tuple[str, str], str], list[_Episode]] = defaultdict(list)
    for episode in sorted(episodes, key=lambda e: (e.clip.name, e.activity.activity_id)):
        key = (episode.clip.group, episode.activity.name)
        for existing in by_key[key]:
            if _overlap(existing.event_ref, episode.event_ref) >= 0.3:
                if episode.activity.actors > existing.activity.actors:
                    merged[merged.index(existing)] = episode
                    by_key[key][by_key[key].index(existing)] = episode
                break
        else:
            by_key[key].append(episode)
            merged.append(episode)

    for episode in merged:
        views = _views(episode, groups, config)
        if len(views) < config.min_views:
            out.skipped["too_few_views"] += 1
            continue
        clip, activity = episode.clip, episode.activity
        slot_id = f"meva:{clip.camera_set}:{clip.slot}"
        out.candidates.append(
            PhaseCandidate(
                candidate_id=f"meva:{clip.name}:{activity.name}:{activity.activity_id}",
                dataset="meva",
                source_video=slot_id,
                event_type=config.event_types.get(activity.name, DEFAULT_EVENT_TYPE),
                activity=activity.name,
                # The clip the activity was annotated in, unless it does not see the whole padded
                # window (it can sit at the edge of its five minutes): then the first view that
                # does.
                primary_view=clip.camera
                if clip.camera in {v.camera for v in views}
                else views[0].camera,
                views=views,
                note=f"{len(views)} synchronised views; annotated in {clip.name}",
            )
        )

    out.candidates = _cap(out.candidates, config)
    out.candidates.sort(key=lambda c: c.candidate_id)
    return out


def _views(
    episode: _Episode, groups: Mapping[tuple[str, str], Sequence[ClipInfo]], config: MevaConfig
) -> list[ViewSpec]:
    """Every clip of the group that sees the whole padded window, cut to that window.

    A clip's frame f is reference frame f + offset, so the window [w0, w1] in reference frames is
    [w0 - offset, w1 - offset] in the clip's own. The primary view comes first.
    """
    w0, w1 = episode.window_ref
    views: list[ViewSpec] = []
    for other in groups[episode.clip.group]:
        start, end = w0 - other.offset, w1 - other.offset
        if start < 0 or end > other.frames:
            continue
        views.append(
            ViewSpec(
                camera=other.camera,
                source_uri=_s3_key(other, config.s3_prefix),
                start_s=start / FPS,
                end_s=end / FPS,
            )
        )
    views.sort(key=lambda v: (v.camera != episode.clip.camera, v.camera))  # annotated view first
    return views


def _keep(
    candidates: Sequence[PhaseCandidate], cap: int | None, key: str, seed: int
) -> list[PhaseCandidate]:
    """At most `cap` per group (`key` names the attribute), chosen by a seeded hash: the same
    selection every time, and not simply the first in the folder."""
    if cap is None:
        return list(candidates)
    groups: dict[str, list[PhaseCandidate]] = defaultdict(list)
    for candidate in candidates:
        groups[getattr(candidate, key) or ""].append(candidate)
    kept: list[PhaseCandidate] = []
    for group in groups.values():
        group.sort(key=lambda c: hashlib.sha256(f"{seed}:{c.candidate_id}".encode()).hexdigest())
        kept.extend(group[:cap])
    return kept


def _cap(candidates: list[PhaseCandidate], config: MevaConfig) -> list[PhaseCandidate]:
    # Slots first: near-duplicates from one scene would otherwise fill the activity's quota.
    kept = _keep(candidates, config.per_slot_cap, "source_video", config.seed)
    return _keep(kept, config.per_activity_cap, "activity", config.seed)


def load_selection(repo: str | Path, config: MevaConfig | None = None) -> Selection:
    """Select from a checkout of the MEVA annotation repo (its `metadata/` and `annotation/`)."""
    root = Path(repo)
    table = read_clip_table(root / "metadata/meva-clip-camera-and-time-table.txt")
    activities: dict[str, list[Activity]] = {}
    for path in sorted(root.glob("annotation/**/*.activities.yml")):
        clip = path.name[: -len(".activities.yml")]
        if clip in table:
            activities.setdefault(clip, []).extend(read_activities(path))
    return select_candidates(activities, table, config or MevaConfig())


def summarise(selection: Selection) -> str:
    lines = ["| Activity | Instances | Candidates |", "|---|---:|---:|"]
    chosen = selection.by_activity()
    for name in sorted(selection.seen, key=lambda n: -selection.seen[n]):
        lines.append(f"| {name} | {selection.seen[name]} | {chosen.get(name, 0)} |")
    lines.append(f"| **all** | {sum(selection.seen.values())} | {len(selection.candidates)} |")
    if selection.skipped:
        lines += [
            "",
            "Left out: " + ", ".join(f"{n} {why}" for why, n in selection.skipped.most_common()),
        ]
    return "\n".join(lines) + "\n"


__all__: Iterable[str] = (
    "Activity",
    "ClipInfo",
    "MevaConfig",
    "Selection",
    "load_selection",
    "parse_clip_name",
    "read_activities",
    "read_clip_table",
    "select_candidates",
    "summarise",
    "sync_groups",
)
