"""Rank fusion and grouping of raw hits into candidate windows (design §10.1). Pure."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field

RRF_K = 60


@dataclass
class Hit:
    """One point returned by a vector or text search."""

    source: str  # frames | tracks | events | image
    key: str  # unique per point
    camera_id: str
    start_ms: int
    end_ms: int
    cosine: float = 0.0
    segment_ids: list[str] = field(default_factory=list)
    keyframe_uri: str | None = None
    crop_uri: str | None = None
    track_id: str | None = None
    category: str | None = None
    colors: list[str] = field(default_factory=list)
    zones: list[str] = field(default_factory=list)
    event_id: str | None = None
    incident_id: str | None = None
    caption: str | None = None
    boost: float = 1.0


@dataclass
class Window:
    camera_id: str
    start_ms: int
    end_ms: int
    score: float = 0.0
    hits: list[Hit] = field(default_factory=list)

    @property
    def result_id(self) -> str:
        raw = f"{self.camera_id}|{self.start_ms // 1000}|{self.end_ms // 1000}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]  # noqa: S324 - an id, not a secret


def rrf_scores(ranked_lists: list[list[Hit]]) -> dict[str, float]:
    """Reciprocal rank fusion over several ranked lists, keyed by `Hit.key`. A hit's own
    `boost` (a matching colour, say) scales its contribution."""
    scores: dict[str, float] = defaultdict(float)
    for hits in ranked_lists:
        for rank, hit in enumerate(hits, start=1):
            scores[hit.key] += hit.boost / (RRF_K + rank)
    return dict(scores)


def group_windows(ranked_lists: list[list[Hit]], *, window_s: float, top_k: int) -> list[Window]:
    """Fuse the lists, then merge hits on one camera that fall within `window_s` of each other
    into a single window. A window's score is the sum of its distinct hits' fused scores, so
    footage that several searches agree on outranks one lucky frame; scores are normalised to
    0..1 by the best window."""
    scores = rrf_scores(ranked_lists)
    unique: dict[str, Hit] = {}
    for hits in ranked_lists:
        for h in hits:
            unique.setdefault(h.key, h)

    by_cam: dict[str, list[Hit]] = defaultdict(list)
    for h in unique.values():
        by_cam[h.camera_id].append(h)

    gap_ms = int(window_s * 1000)
    windows: list[Window] = []
    for cam, hits in by_cam.items():
        hits.sort(key=lambda h: h.start_ms)
        current: Window | None = None
        for h in hits:
            if current is not None and h.start_ms - current.end_ms <= gap_ms:
                current.end_ms = max(current.end_ms, h.end_ms)
                current.hits.append(h)
                current.score += scores[h.key]
            else:
                if current is not None:
                    windows.append(current)
                current = Window(cam, h.start_ms, h.end_ms, scores[h.key], [h])
        if current is not None:
            windows.append(current)

    windows.sort(key=lambda w: (-w.score, w.start_ms))
    windows = windows[:top_k]
    if windows:
        top = windows[0].score or 1.0
        for w in windows:
            w.score = round(min(1.0, w.score / top), 4)
    return windows
