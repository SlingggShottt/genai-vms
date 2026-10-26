"""The retrieval benchmark's metrics (P4-J6). Pure: windows and places are `(start, end)` epoch
seconds on one camera, best result first.

A result window is *relevant* when it overlaps a relevant place by at least `MIN_OVERLAP_S`.

* `R@k`: the share of queries with a relevant window among the first k results (the usual recall
  of moment retrieval: a query is answered or it is not).
* `AP@k`: average precision with the relevant *places* as the items to find. Each rank at which a
  result first reaches a place not reached before contributes the precision at that rank; the sum
  is divided by the number of places, so a place never reached counts as zero. Averaged over
  queries it is mAP.
* `tIoU@t` (R1@IoU): whether the first result's temporal IoU with some relevant place is at least
  `t`. Stricter than overlap: a 10 s window on a 5 s clip scores at best 0.5.
* stage latency: the median and 95th percentile of each stage's time across queries.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence

MIN_OVERLAP_S = 2.0
KS = (1, 5, 10)
TIOU = (0.3, 0.5)

Window = tuple[float, float]


def overlap(a: Window, b: Window) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def tiou(a: Window, b: Window) -> float:
    inter = overlap(a, b)
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union > 0 else 0.0


def reaches(window: Window, place: Window) -> bool:
    return overlap(window, place) >= MIN_OVERLAP_S


def recall_at(ranked: Sequence[Window], places: Sequence[Window], k: int) -> float:
    """1.0 if any of the first k windows is relevant, else 0.0 (averaged over queries: R@k)."""
    return float(any(reaches(w, p) for w in ranked[:k] for p in places))


def average_precision(ranked: Sequence[Window], places: Sequence[Window], k: int = 10) -> float:
    """AP@k with the relevant places as the items; 0.0 when there are none to find."""
    if not places:
        return 0.0
    reached: set[int] = set()
    total = 0.0
    for rank, window in enumerate(ranked[:k], start=1):
        fresh = {i for i, p in enumerate(places) if i not in reached and reaches(window, p)}
        if fresh:
            reached |= fresh
            total += len(reached) / rank
    return total / len(places)


def tiou_at(ranked: Sequence[Window], places: Sequence[Window], threshold: float) -> float:
    """1.0 if the first result overlaps some relevant place with tIoU of at least `threshold`."""
    if not ranked:
        return 0.0
    return float(any(tiou(ranked[0], p) >= threshold for p in places))


def query_scores(ranked: Sequence[Window], places: Sequence[Window]) -> dict[str, float]:
    out = {f"R@{k}": recall_at(ranked, places, k) for k in KS}
    out["AP@10"] = average_precision(ranked, places, 10)
    for t in TIOU:
        out[f"tIoU@{t}"] = tiou_at(ranked, places, t)
    return out


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile (q in 0..100); nan for no values."""
    if not values:
        return math.nan
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(q / 100 * len(ordered)) - 1))]


def stage_latency(timings: Sequence[Mapping[str, float]]) -> dict[str, dict[str, float]]:
    """Median and p95 (milliseconds) of every stage that any query reported, with `total`."""
    stages = sorted({s for t in timings for s in t})
    out = {}
    for stage in stages:
        values = [t[stage] for t in timings if stage in t]
        out[stage] = {
            "median_ms": round(statistics.median(values), 1),
            "p95_ms": round(percentile(values, 95), 1),
            "n": len(values),
        }
    return out


def mean_of(rows: Sequence[Mapping[str, float]], key: str) -> float:
    values = [r[key] for r in rows if key in r]
    return round(statistics.fmean(values), 3) if values else math.nan
