"""A first batch of candidates for the annotators, and who gets which.

`meva-candidates` finds hundreds of clips; nobody labels them all at once. A batch is a small,
varied selection, split so that each annotator has some clips of their own and a set that **both**
label, which is what the agreement figure (`phase-agreement`) is computed on.

- *Varied*: the rare activities (a package left behind, a theft) go in whenever they exist, then the
  rest are taken round-robin across activities, so no one activity fills the batch. At most one
  clip per `source_video` (a camera set and five-minute slot) while there are others to take: two
  clips a minute apart on the same cameras are near-duplicates and would count twice.
- *Reproducible*: the same candidates, size and seed give the same batch.
"""

from __future__ import annotations

import random
import re
from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from annotation_kit.candidates import PhaseCandidate

RARE_AT_MOST = 5  # an activity with this few candidates or fewer is rare: all of them are taken
_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")


def _kind(candidate: PhaseCandidate) -> str:
    return candidate.activity or candidate.event_type


def _interleave(groups: dict[str, list[PhaseCandidate]]) -> list[PhaseCandidate]:
    """One from each group in turn, groups in name order, until all are empty."""
    queues = {kind: list(items) for kind, items in sorted(groups.items())}
    out: list[PhaseCandidate] = []
    while any(queues.values()):
        for kind in queues:
            if queues[kind]:
                out.append(queues[kind].pop(0))
    return out


def too_long(candidates: Sequence[PhaseCandidate], max_duration_s: float | None) -> int:
    """How many candidates a duration limit would leave out."""
    if max_duration_s is None:
        return 0
    return sum(1 for c in candidates if c.duration_s > max_duration_s)


def pick_batch(
    candidates: Sequence[PhaseCandidate],
    size: int,
    *,
    seed: int = 0,
    max_duration_s: float | None = None,
    exclude: Collection[str] = (),
) -> list[PhaseCandidate]:
    """At most `size` candidates, varied across activities, in an order that mixes them. Clips
    longer than `max_duration_s` are never chosen (they would not fit the labelling timeline), nor
    are the `exclude`d ids (a clip found unusable after it was cut)."""
    if size < 1:
        raise ValueError("a batch needs at least one clip")
    if max_duration_s is not None:
        candidates = [c for c in candidates if c.duration_s <= max_duration_s]
    if exclude:
        candidates = [c for c in candidates if c.candidate_id not in set(exclude)]
    rng = random.Random(seed)  # noqa: S311 - sampling, not security
    pool: dict[str, list[PhaseCandidate]] = defaultdict(list)
    for candidate in sorted(candidates, key=lambda c: c.candidate_id):
        pool[_kind(candidate)].append(candidate)
    for group in pool.values():
        rng.shuffle(group)

    chosen: dict[str, list[PhaseCandidate]] = defaultdict(list)
    taken = 0
    for kind, group in sorted(pool.items()):  # the rare ones first, all of them
        if len(group) <= RARE_AT_MOST:
            for candidate in group[: size - taken]:
                chosen[kind].append(candidate)
                taken += 1
            group.clear()

    used_sources = {c.source_video for group in chosen.values() for c in group}
    for distinct in (True, False):  # first pass: new source videos only; second: anything left
        progress = True
        while taken < size and progress:
            progress = False
            for kind, group in sorted(pool.items()):
                if taken >= size:
                    break
                pick = next(
                    (
                        i
                        for i, c in enumerate(group)
                        if not distinct or c.source_video not in used_sources
                    ),
                    None,
                )
                if pick is None:
                    continue
                candidate = group.pop(pick)
                chosen[kind].append(candidate)
                used_sources.add(candidate.source_video)
                taken += 1
                progress = True
    return _interleave(chosen)


@dataclass(frozen=True)
class Assignment:
    """What each annotator labels: the `shared` clips (everyone) plus their `own` ones."""

    shared: tuple[PhaseCandidate, ...]
    own: dict[str, tuple[PhaseCandidate, ...]]
    seed: int = 0

    def for_annotator(self, name: str) -> list[PhaseCandidate]:
        """Shared and own clips together, in an order particular to this annotator, so the shared
        ones are not all met first (or in the same order) by everyone."""
        clips = [*self.shared, *self.own[name]]
        random.Random(f"{self.seed}:{name}").shuffle(clips)  # noqa: S311 - ordering, not security
        return clips


def split_batch(
    batch: Sequence[PhaseCandidate], annotators: Sequence[str], *, overlap: int, seed: int = 0
) -> Assignment:
    """`overlap` clips, spread evenly through the batch, go to everyone; the rest are dealt out in
    turn. Agreement needs two people on the same clips, so overlap with one annotator is refused."""
    names = list(annotators)
    if not names or len(set(names)) != len(names):
        raise ValueError("give each annotator once")
    if bad := [n for n in names if not _NAME.match(n)]:
        raise ValueError(f"annotator names are lower-case words (they name files): {bad}")
    if overlap < 0 or overlap > len(batch):
        raise ValueError(f"overlap must be from 0 to the batch size ({len(batch)}), got {overlap}")
    if overlap and len(names) < 2:
        raise ValueError("an overlap needs at least two annotators")

    step = len(batch) / overlap if overlap else 0
    shared_at = {int(i * step + step / 2) for i in range(overlap)}
    shared = tuple(c for i, c in enumerate(batch) if i in shared_at)
    rest = [c for i, c in enumerate(batch) if i not in shared_at]
    own = {name: tuple(rest[i :: len(names)]) for i, name in enumerate(names)}
    return Assignment(shared=shared, own=own, seed=seed)


def summarise(batch: Sequence[PhaseCandidate], assignment: Assignment) -> str:
    kinds: dict[str, int] = defaultdict(int)
    for candidate in batch:
        kinds[_kind(candidate)] += 1
    lines = [
        f"{len(batch)} clips: {len(assignment.shared)} labelled by everyone, "
        + ", ".join(f"{len(v)} only by {k}" for k, v in assignment.own.items()),
        "",
        "| activity | clips |",
        "|---|---|",
        *(f"| {kind} | {n} |" for kind, n in sorted(kinds.items())),
        "",
        "| annotator | clips to label | views |",
        "|---|---|---|",
    ]
    for name in assignment.own:
        clips = assignment.for_annotator(name)
        views = ", ".join(
            f"{n} with {v} views"
            for v, n in sorted(
                {
                    len(c.views): sum(len(x.views) == len(c.views) for x in clips) for c in clips
                }.items()
            )
        )
        lines.append(f"| {name} | {len(clips)} | {views} |")
    return "\n".join(lines)
