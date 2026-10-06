"""TG evaluation (P5-D3): how well does a method place the stages of an incident?

    uv run python ml/evaluation/reasoning/phase/evaluate.py --dataset datasets/tg-v1 --split test \
        --methods rules,model --label "zero-shot qwen2.5vl:3b"

Runs on a dataset made by `ml/training/tg/build_dataset.py` (its `test.jsonl` and frames). Two
methods, scored the same way:

- `rules`: the detector's own timing, no model (what the reasoning service falls back to):
  the flagged span is the action, a lead-in before it is escalation then precursor, and so on.
- `model`: the sample's prompt and frames go to the `phase_tg` task of the real gateway, the
  per-frame answer becomes spans with the service's own `spans_from_labels`, and an unusable
  answer falls back to the rules timeline exactly as the service does. Point it at the zero-shot
  base model or, once one exists, at the trained adapter (`--label` names the run).

Scores: mIoU over stages (per sample, over every stage the truth or the answer has, then the
mean over samples), boundary error in seconds (between consecutive true stages, where the answer
has both), per-frame accuracy on usable answers, and how often the model's answer was usable.
Every figure that is a mean over samples comes with a 95 % bootstrap interval, because a test
set of a few dozen clips cannot support more than that.

What it does not do: judge anything but the stage timing (the PhaVR captions are a different
evaluation), compare against a cloud model (`--task` can name one, nothing here sets it up), or
tell you anything about footage unlike the dataset.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from reasoning.domain.timeline import FrameLabels, rule_spans, spans_from_labels
from vms_common.llm import ImageInput, LLMError

EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
Span = tuple[str, float, float]  # (stage, start_s, end_s)


@dataclass(frozen=True)
class Sample:
    id: str
    event_type: str
    n_views: int
    window_s: float
    frame_times: list[float]
    labels: list[str]
    truth: list[Span]
    flagged: tuple[float, float]
    prompt: str
    images: list[Path]


def load_samples(dataset: Path, split: str) -> list[Sample]:
    out = []
    for line in (dataset / f"{split}.jsonl").read_text().splitlines():
        r = json.loads(line)
        user = r["messages"][0]["content"]
        out.append(
            Sample(
                id=r["id"],
                event_type=r["event_type"],
                n_views=r["n_views"],
                window_s=r["window_s"],
                frame_times=r["frame_times"],
                labels=r["labels"],
                truth=[(p["phase"], p["start_s"], p["end_s"]) for p in r["phases"]],
                flagged=(r["flagged_span"][0], r["flagged_span"][1]),
                prompt=next(c["text"] for c in user if c["type"] == "text"),
                images=[dataset / p for p in r["images"]],
            )
        )
    return out


# ---- metrics (pure) -----------------------------------------------------------------------------


def overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def stage_iou(truth: list[Span], pred: list[Span]) -> dict[str, float]:
    """IoU in seconds of each stage the truth or the answer has."""
    out = {}
    for stage in {s for s, _, _ in truth} | {s for s, _, _ in pred}:
        t = [(a, b) for s, a, b in truth if s == stage]
        p = [(a, b) for s, a, b in pred if s == stage]
        inter = sum(overlap(x, y) for x in t for y in p)
        union = sum(b - a for a, b in t) + sum(b - a for a, b in p) - inter
        out[stage] = inter / union if union > 0 else 0.0
    return out


def sample_miou(truth: list[Span], pred: list[Span]) -> float:
    ious = stage_iou(truth, pred)
    return statistics.fmean(ious.values()) if ious else 0.0


def boundaries(spans: list[Span]) -> dict[tuple[str, str], float]:
    """Where one stage hands over to the next: {(stage, next stage): time}."""
    return {(a[0], b[0]): (a[2] + b[1]) / 2 for a, b in zip(spans, spans[1:], strict=False)}


def boundary_errors(truth: list[Span], pred: list[Span]) -> tuple[list[float], int]:
    """Absolute error (s) of each true boundary the answer also has, and how many it lacks."""
    want, got = boundaries(truth), boundaries(pred)
    errors = [abs(got[k] - t) for k, t in want.items() if k in got]
    return errors, len(want) - len(errors)


def labels_at(spans: list[Span], times: list[float]) -> list[str]:
    """The stage a span list puts at each time; a time outside every span takes the nearest."""
    out = []
    for t in times:
        # a span that contains the time beats any that merely ends or starts at it
        best = min(
            spans, key=lambda s: -1.0 if s[1] <= t < s[2] else min(abs(t - s[1]), abs(t - s[2]))
        )
        out.append(best[0])
    return out


def bootstrap_ci(values: list[float], seed: int = 0, n: int = 2000) -> tuple[float, float]:
    """95 % interval of the mean; (nan, nan) for fewer than two values."""
    if len(values) < 2:
        return float("nan"), float("nan")
    rng = random.Random(seed)  # noqa: S311 - resampling, not security
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


# ---- predictors ---------------------------------------------------------------------------------


def _seconds(dt: datetime) -> float:
    return (dt - EPOCH).total_seconds()


def rules_spans(s: Sample) -> list[Span]:
    spans = rule_spans(
        window_start=EPOCH,
        window_end=EPOCH + timedelta(seconds=s.window_s),
        event_start=EPOCH + timedelta(seconds=s.flagged[0]),
        event_end=EPOCH + timedelta(seconds=s.flagged[1]),
    )
    return [(p.phase, _seconds(p.start), _seconds(p.end)) for p in spans]


class Gateway(Protocol):
    async def vision(self, task: str, prompt: str, images: list[ImageInput], **kw): ...


@dataclass
class Prediction:
    spans: list[Span]  # what the pipeline would output (rules fallback applied)
    usable: bool  # the model's own answer produced spans
    labels: list[str] | None  # the model's per-frame answer when it had the right length
    seconds: float = 0.0
    error: str = ""


async def model_prediction(gateway: Gateway, task: str, s: Sample) -> Prediction:
    started = time.perf_counter()
    try:
        images = [ImageInput(data=p.read_bytes()) for p in s.images]
        result = await gateway.vision(task, s.prompt, images, response_model=FrameLabels)
        labels = result.parsed.phases
    except LLMError as exc:
        return Prediction(
            rules_spans(s), False, None, time.perf_counter() - started, str(exc)[:120]
        )
    seconds = time.perf_counter() - started
    spans = spans_from_labels(
        labels,
        [EPOCH + timedelta(seconds=t) for t in s.frame_times],
        window_start=EPOCH,
        window_end=EPOCH + timedelta(seconds=s.window_s),
        source="eval",
    )
    right_length = list(labels) if len(labels) == len(s.frame_times) else None
    if spans is None:
        return Prediction(rules_spans(s), False, right_length, seconds)
    return Prediction(
        [(p.phase, _seconds(p.start), _seconds(p.end)) for p in spans], True, right_length, seconds
    )


# ---- scoring ------------------------------------------------------------------------------------


@dataclass
class Scores:
    miou: list[float] = field(default_factory=list)
    boundary: list[float] = field(default_factory=list)
    unmatched_boundaries: int = 0
    frame_accuracy: list[float] = field(default_factory=list)
    usable: list[float] = field(default_factory=list)
    seconds: list[float] = field(default_factory=list)
    errors: int = 0
    by_type: dict[str, list[float]] = field(default_factory=dict)
    by_views: dict[str, list[float]] = field(default_factory=dict)

    def add(self, s: Sample, p: Prediction, *, model: bool) -> None:
        m = sample_miou(s.truth, p.spans)
        self.miou.append(m)
        self.by_type.setdefault(s.event_type, []).append(m)
        self.by_views.setdefault("1 view" if s.n_views == 1 else f"{s.n_views} views", []).append(m)
        errs, missing = boundary_errors(s.truth, p.spans)
        self.boundary += errs
        self.unmatched_boundaries += missing
        labels = p.labels if model else labels_at(p.spans, s.frame_times)
        if labels is not None and (not model or p.usable):
            self.frame_accuracy.append(
                sum(a == b for a, b in zip(labels, s.labels, strict=True)) / len(s.labels)
            )
        if model:
            self.usable.append(float(p.usable))
            self.seconds.append(p.seconds)
            self.errors += bool(p.error)

    def summary(self) -> dict:
        def mean_ci(values: list[float]) -> dict:
            lo, hi = bootstrap_ci(values)
            return {
                "n": len(values),
                "mean": round(statistics.fmean(values), 3) if values else None,
                "ci95": [round(lo, 3), round(hi, 3)],
            }

        return {
            "miou": mean_ci(self.miou),
            "boundary_mae_s": mean_ci(self.boundary),
            "boundaries_not_in_answer": self.unmatched_boundaries,
            "frame_accuracy": mean_ci(self.frame_accuracy),
            "usable_answer_rate": mean_ci(self.usable) if self.usable else None,
            "seconds_per_sample_median": round(statistics.median(self.seconds), 2)
            if self.seconds
            else None,
            "gateway_errors": self.errors,
            "miou_by_event_type": {k: mean_ci(v) for k, v in sorted(self.by_type.items())},
            "miou_by_views": {k: mean_ci(v) for k, v in sorted(self.by_views.items())},
        }


async def evaluate(
    samples: list[Sample], methods: list[str], gateway: Gateway | None, task: str, label: str
) -> dict:
    out: dict = {"samples": len(samples), "methods": {}}
    if "rules" in methods:
        sc = Scores()
        for s in samples:
            sc.add(s, Prediction(rules_spans(s), True, None), model=False)
        out["methods"]["rules (detector timing, no model)"] = sc.summary()
    if "model" in methods:
        if gateway is None:
            raise ValueError("the model method needs a gateway")
        sc = Scores()
        for i, s in enumerate(samples, 1):
            sc.add(s, await model_prediction(gateway, task, s), model=True)
            print(f"  model {i}/{len(samples)}", flush=True)
        out["methods"][label] = sc.summary()
    return out


def markdown(report: dict, dataset: str, split: str) -> str:
    def cell(d: dict | None, unit: str = "") -> str:
        if not d or d["mean"] is None:
            return "–"
        lo, hi = d["ci95"]
        return f"{d['mean']}{unit} ({lo}–{hi}, n={d['n']})"

    lines = [
        f"# TG evaluation — `{dataset}` / `{split}` ({report['samples']} samples)",
        "",
        "Mean over samples with a 95 % bootstrap interval and n. mIoU is over the stages the truth "
        "or the answer has; boundary error is between consecutive true stages that the answer "
        "also has.",
        "",
        "| method | mIoU | boundary error | frame accuracy | usable answers | s/sample |",
        "|---|---|---|---|---|---|",
    ]
    for name, m in report["methods"].items():
        secs = m["seconds_per_sample_median"]
        lines.append(
            f"| {name} | {cell(m['miou'])} | {cell(m['boundary_mae_s'], ' s')} | "
            f"{cell(m['frame_accuracy'])} | {cell(m['usable_answer_rate'])} | "
            f"{secs if secs is not None else '–'} |"
        )
    for name, m in report["methods"].items():
        lines += ["", f"## {name}", "", "| by | mIoU |", "|---|---|"]
        for group in ("miou_by_event_type", "miou_by_views"):
            for k, v in m[group].items():
                lines.append(f"| {k} | {cell(v)} |")
        lines.append("")
        lines.append(
            f"{m['boundaries_not_in_answer']} true boundaries were not in the answer; "
            f"{m['gateway_errors']} gateway errors."
        )
    return "\n".join(lines) + "\n"


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--split", default="test")
    ap.add_argument("--methods", default="rules,model")
    ap.add_argument("--label", default="model (zero-shot)", help="what to call the model run")
    ap.add_argument("--task", default="phase_tg", help="gateway task name (config/models.yaml)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--redis-url", default="redis://localhost:6379/9", help="scratch db: lease + cache"
    )
    ap.add_argument("--out", type=Path, default=None, help="write <out>.json and <out>.md")
    args = ap.parse_args()

    samples = load_samples(args.dataset, args.split)
    if args.limit:
        samples = samples[: args.limit]
    methods = args.methods.split(",")
    gateway = redis = None
    if "model" in methods:
        from redis.asyncio import Redis
        from vms_common.config import LLMSettings
        from vms_common.llm import LLMGateway

        redis = Redis.from_url(args.redis_url, decode_responses=True)
        await redis.flushdb()  # a cached answer would be timed as a model call
        gateway = LLMGateway.from_settings(LLMSettings(), redis=redis)
    try:
        report = await evaluate(samples, methods, gateway, args.task, args.label)
    finally:
        if gateway is not None:
            await gateway.aclose()
        if redis is not None:
            await redis.flushdb()
            await redis.aclose()
    text = markdown(report, args.dataset.name, args.split)
    print(text)
    if args.out:
        args.out.with_suffix(".json").write_text(json.dumps(report, indent=1) + "\n")
        args.out.with_suffix(".md").write_text(text)


if __name__ == "__main__":
    asyncio.run(main())
