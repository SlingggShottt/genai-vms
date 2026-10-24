"""Read a finished run closer than the table does.

    uv run python ml/evaluation/reasoning/phase/analyse.py --dataset datasets/tg-v1 --split all \
        --predictions answers.jsonl

The table of `evaluate.py` scores an unusable model answer as the rules timeline (what the service
does), so a model that fails to answer one time in three borrows a third of its score from the
rules. This says what the table hides: how often the model gave an answer at all, how it does on
those answers against the rules on the same clips, which stages it ever says, and whether it fails
more with more frames.
"""

from __future__ import annotations

import argparse
import importlib.util
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("tg_evaluate_for_analysis", HERE / "evaluate.py")
if _spec is None or _spec.loader is None:
    raise ImportError("cannot load evaluate.py")
ev = importlib.util.module_from_spec(_spec)
sys.modules["tg_evaluate_for_analysis"] = ev
_spec.loader.exec_module(ev)


def analyse(samples: dict[str, ev.Sample], predictions: dict[str, ev.Prediction]) -> dict:
    missing = sorted(set(samples) - set(predictions))
    if missing:
        raise ValueError(f"{len(missing)} samples have no answer yet, e.g. {missing[0]}")
    answered = [i for i in samples if predictions[i].usable]
    model = {i: ev.sample_miou(samples[i].truth, predictions[i].spans) for i in answered}
    rules = {i: ev.sample_miou(samples[i].truth, ev.rules_spans(samples[i])) for i in answered}
    said, true = Counter(), Counter()
    for i in answered:
        said.update(predictions[i].labels or [])
        true.update(samples[i].labels)
    by_frames: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for i, s in samples.items():
        row = by_frames[len(s.frame_times)]
        row[0] += not predictions[i].usable
        row[1] += 1
    by_source: dict[str, list[list[float]]] = defaultdict(lambda: [[], []])
    by_exact: dict[str, list[list[float]]] = defaultdict(lambda: [[], []])
    for i in answered:
        for table, key in (
            (by_source, ev.source_group(samples[i].label_source)),
            (by_exact, _exact(samples[i].label_source)),
        ):
            table[key][0].append(model[i])
            table[key][1].append(rules[i])
    n = len(samples)
    return {
        "samples": n,
        "answered": len(answered),
        "answered_share": round(len(answered) / n, 3) if n else None,
        "gateway_errors": sum(bool(p.error) for p in predictions.values()),
        "model_miou_on_answered": _mean(model.values()),
        "rules_miou_on_same": _mean(rules.values()),
        "model_better": sum(model[i] > rules[i] for i in answered),
        "model_worse": sum(model[i] < rules[i] for i in answered),
        "ties": sum(model[i] == rules[i] for i in answered),
        "stages_the_model_said": dict(sorted(said.items())),
        "stages_true_on_those": dict(sorted(true.items())),
        "unanswered_by_frames": {k: f"{v[0]}/{v[1]}" for k, v in sorted(by_frames.items())},
        "by_source": {
            g: {"n": len(a), "model": _mean(a), "rules": _mean(b)}
            for g, (a, b) in sorted(by_source.items())
        },
        "by_exact_source": {
            g: {"n": len(a), "model": _mean(a), "rules": _mean(b)}
            for g, (a, b) in sorted(by_exact.items())
        },
    }


def _exact(source: str) -> str:
    """The kind of source without the draft's version: `human:corrected-draft:v1` becomes
    `human:corrected-draft`, `draft:v2:padding-rule` becomes `draft:padding-rule`."""
    parts = source.split(":")
    if parts[0] == "human" and len(parts) > 2:
        return ":".join(parts[:2])
    if parts[0] == "draft" and len(parts) > 2:
        return f"draft:{parts[2]}"
    return source


def _mean(values) -> float | None:  # noqa: ANN001
    values = list(values)
    return round(statistics.fmean(values), 3) if values else None


def markdown(r: dict) -> str:
    lines = [
        f"{r['answered']} of {r['samples']} samples got a usable answer from the model "
        f"({r['answered_share']:.0%}); {r['gateway_errors']} calls failed outright.",
        "",
        f"On those {r['answered']} answers alone: model mIoU **{r['model_miou_on_answered']}**, "
        f"rules on the same clips **{r['rules_miou_on_same']}**; the model was better on "
        f"{r['model_better']}, worse on {r['model_worse']}, equal on {r['ties']}.",
        "",
        f"Stages the model ever said: {r['stages_the_model_said']}. "
        f"True stages on the same clips: {r['stages_true_on_those']}.",
        "",
        "| frames shown | no usable answer |",
        "|---|---|",
        *(f"| {k} | {v} |" for k, v in r["unanswered_by_frames"].items()),
        "",
        "| labels made by | answered clips | model | rules |",
        "|---|---|---|---|",
        *(f"| {g} | {v['n']} | {v['model']} | {v['rules']} |" for g, v in r["by_source"].items()),
        "",
        "| exact source | answered clips | model | rules |",
        "|---|---|---|---|",
        *(
            f"| {g} | {v['n']} | {v['model']} | {v['rules']} |"
            for g, v in r["by_exact_source"].items()
        ),
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--split", default="all")
    ap.add_argument("--predictions", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    samples = {s.id: s for s in ev.load_samples(args.dataset, args.split)}
    text = markdown(analyse(samples, ev.read_predictions(args.predictions)))
    print(text)
    if args.out:
        args.out.write_text(text)


if __name__ == "__main__":
    main()
