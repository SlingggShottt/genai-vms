"""Two runs on the same clips, paired.

    uv run python ml/evaluation/reasoning/phase/compare.py --dataset datasets/tg-v1 --split test \
        --a base-answers.jsonl --b adapter-answers.jsonl --names "zero-shot" "adapter"

The table of `evaluate.py` gives each run's mean with an interval; two such intervals that overlap
say little about whether one run is better, because the clips differ far more than the runs do.
This scores both runs on every clip and takes the difference clip by clip, so the interval is the
interval of the *difference*. It is given for all clips and for each source of the labels
(`annotation_kit.combine.group`): a gain that shows on one source only (say, labels a rule made)
is a gain at reproducing that source, which is not the same as seeing the stages.

A clip where the run gave no usable answer is scored as the rules timeline, as in the table.
"""

from __future__ import annotations

import argparse
import importlib.util
import statistics
import sys
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("tg_evaluate_for_compare", HERE / "evaluate.py")
if _spec is None or _spec.loader is None:
    raise ImportError("cannot load evaluate.py")
ev = importlib.util.module_from_spec(_spec)
sys.modules["tg_evaluate_for_compare"] = ev
_spec.loader.exec_module(ev)

from stats import bootstrap_ci  # noqa: E402

TIE = 0.01  # a difference under one point of mIoU counts as a tie


def compare(
    samples: Mapping[str, ev.Sample],
    a: Mapping[str, ev.Prediction],
    b: Mapping[str, ev.Prediction],
) -> dict:
    """Per-clip mIoU of `b` minus `a`, overall and by label source."""
    missing = sorted(i for i in samples if i not in a or i not in b)
    if missing:
        raise ValueError(f"{len(missing)} clips lack an answer in one run, e.g. {missing[0]}")
    rows: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for i, s in samples.items():
        pair = (ev.sample_miou(s.truth, a[i].spans), ev.sample_miou(s.truth, b[i].spans))
        rows["all clips"].append(pair)
        rows[ev.source_group(s.label_source)].append(pair)
    return {name: _row(pairs) for name, pairs in rows.items()}


def _row(pairs: list[tuple[float, float]]) -> dict:
    diffs = [y - x for x, y in pairs]
    lo, hi = bootstrap_ci(diffs)
    return {
        "n": len(pairs),
        "a": statistics.fmean(x for x, _ in pairs),
        "b": statistics.fmean(y for _, y in pairs),
        "difference": statistics.fmean(diffs),
        "ci95": (lo, hi),
        "b_better": sum(d > TIE for d in diffs),
        "tied": sum(abs(d) <= TIE for d in diffs),
        "b_worse": sum(d < -TIE for d in diffs),
    }


def markdown(result: Mapping[str, dict], names: tuple[str, str]) -> str:
    a, b = names
    lines = [
        f"| clips | n | {a} | {b} | {b} − {a} (95 % interval) | {b} better / tied / worse |",
        "|---|---:|---:|---:|---|---|",
    ]
    ordered = sorted(result, key=lambda k: (k != "all clips", k))
    for name in ordered:
        r = result[name]
        lo, hi = r["ci95"]
        interval = "n/a" if lo != lo else f"{lo:+.3f} to {hi:+.3f}"
        lines.append(
            f"| {name} | {r['n']} | {r['a']:.3f} | {r['b']:.3f} | {r['difference']:+.3f} "
            f"({interval}) | {r['b_better']} / {r['tied']} / {r['b_worse']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--split", default="test")
    ap.add_argument("--a", type=Path, required=True, help="answers of the first run")
    ap.add_argument("--b", type=Path, required=True, help="answers of the second run")
    ap.add_argument("--names", nargs=2, default=("a", "b"))
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    samples = {s.id: s for s in ev.load_samples(args.dataset, args.split)}
    text = markdown(
        compare(samples, ev.read_predictions(args.a), ev.read_predictions(args.b)),
        tuple(args.names),
    )
    print(text)
    if args.out:
        args.out.write_text(text)


if __name__ == "__main__":
    main()
