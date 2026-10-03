"""How much people changed the model's drafts (the pseudo-label edit rate).

The draft is only worth having if checking it is cheaper than writing from nothing, and the labels
are only worth training on if people really looked. Both are answered by how often a person changed
the draft. A rate near 0 % across the board is as suspicious as one near 100 %: it can mean a
perfect model, or annotators accepting without reading. Spot-check before trusting it.

Every number is over labels that *had* a draft; a label with none is counted but not averaged in.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from annotation_kit.schema import PhavrLabel


@dataclass
class EditStats:
    labels: int = 0  # verified labels
    drafted: int = 0  # ... of which the model had drafted
    captions_changed: int = 0
    dissimilarity_sum: float = 0.0
    answers: int = 0
    answers_changed: int = 0
    untouched: int = 0  # no caption change and no answer change

    @property
    def caption_edit_rate(self) -> float | None:
        return self.captions_changed / self.drafted if self.drafted else None

    @property
    def caption_mean_dissimilarity(self) -> float | None:
        """0 = every caption kept as drafted, 1 = every caption entirely rewritten."""
        return self.dissimilarity_sum / self.drafted if self.drafted else None

    @property
    def answer_change_rate(self) -> float | None:
        return self.answers_changed / self.answers if self.answers else None

    @property
    def untouched_rate(self) -> float | None:
        return self.untouched / self.drafted if self.drafted else None

    def add(self, label: PhavrLabel) -> None:
        self.labels += 1
        if label.edits is None:  # no draft (the schema keeps `pseudo` and `edits` together)
            return
        self.drafted += 1
        self.captions_changed += label.edits.caption_changed
        self.dissimilarity_sum += 1 - label.edits.caption_similarity
        self.answers += len(label.vqa)
        self.answers_changed += len(label.edits.answers_changed)
        self.untouched += not label.edits.caption_changed and not label.edits.answers_changed

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "labels": self.labels,
            "drafted": self.drafted,
            "caption_edit_rate": self.caption_edit_rate,
            "caption_mean_dissimilarity": self.caption_mean_dissimilarity,
            "answer_change_rate": self.answer_change_rate,
            "untouched_rate": self.untouched_rate,
        }


@dataclass
class EditReport:
    overall: EditStats = field(default_factory=EditStats)
    by_event_type: dict[str, EditStats] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "overall": self.overall.as_dict(),
            "by_event_type": {k: v.as_dict() for k, v in sorted(self.by_event_type.items())},
            "skipped": dict(self.skipped),
        }


def edit_report(
    labels: Iterable[PhavrLabel], *, skipped: Mapping[str, Sequence[str]] | None = None
) -> EditReport:
    report = EditReport(
        skipped={reason: len(keys) for reason, keys in (skipped or {}).items() if keys}
    )
    by_type: dict[str, EditStats] = defaultdict(EditStats)
    for label in labels:
        report.overall.add(label)
        by_type[label.event_type].add(label)
    report.by_event_type = dict(by_type)
    return report


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def render_markdown(report: EditReport) -> str:
    rows = [("all", report.overall), *sorted(report.by_event_type.items())]
    lines = [
        "| Event type | Verified | Drafted | Captions edited | Caption rewrite "
        "| Answers changed | Untouched |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, stats in rows:
        lines.append(
            f"| {name} | {stats.labels} | {stats.drafted} | {_pct(stats.caption_edit_rate)} | "
            f"{_pct(stats.caption_mean_dissimilarity)} | {_pct(stats.answer_change_rate)} | "
            f"{_pct(stats.untouched_rate)} |"
        )
    if report.skipped:
        lines += [
            "",
            "Skipped: " + ", ".join(f"{n} {reason}" for reason, n in report.skipped.items()),
        ]
    return "\n".join(lines) + "\n"
