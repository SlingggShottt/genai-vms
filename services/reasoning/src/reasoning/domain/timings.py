"""How long each model-driven step of one analysis took, for the incident's provenance (P5-J4).

The report says which models answered; this says what that cost and which views were skipped:
a stage × camera that held no usable frame is recorded as `answered: false` with no seconds
wasted on it, so a reader of the provenance can tell "nothing to read" from "slow"."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


class CallLog:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def add(self, step: str, seconds: float, **detail: Any) -> None:
        self.rows.append({"step": step, "seconds": round(seconds, 2), **detail})

    def summary(self) -> dict[str, Any]:
        by_step: dict[str, float] = defaultdict(float)
        for row in self.rows:
            by_step[row["step"]] += row["seconds"]
        return {
            "calls": list(self.rows),
            "seconds_by_step": {k: round(v, 2) for k, v in by_step.items()},
            "total_s": round(sum(by_step.values()), 2),
            "views_skipped": sum(
                1 for r in self.rows if r["step"] == "reading" and not r.get("answered", True)
            ),
        }
