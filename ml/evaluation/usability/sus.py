"""Score a usability session (P7-J5): SUS per participant, and task success, time and help per task.

    uv run python ml/evaluation/usability/sus.py --sus sus.csv --tasks tasks.csv [--out report.md]

`sus.csv` and `tasks.csv` follow the templates next to this file (one row per participant and one
row per participant and task). Nothing here needs a model or a network.

A SUS score is only meaningful across a group, so the report gives the mean with a 95 % bootstrap
interval and the spread, never a verdict for one person; with fewer than five participants it says
so. The adjective bands are Bangor, Kortum and Miller's (2009) mapping of a mean score to a word and
are a rough guide, not a result.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # for `stats`

from stats import mean_ci  # noqa: E402

ITEMS = 10
BANDS = [
    (85.5, "excellent"),
    (72.75, "good"),
    (52.0, "ok"),
    (38.0, "poor"),
    (0.0, "worst imaginable"),
]
MIN_GROUP = 5


def sus_score(answers: list[int]) -> float:
    """0-100 from ten answers on a 1-5 scale: odd items count (answer - 1), even items (5 - answer),
    the sum times 2.5."""
    if len(answers) != ITEMS:
        raise ValueError(f"SUS has {ITEMS} items, got {len(answers)}")
    if any(not 1 <= a <= 5 for a in answers):
        raise ValueError("every answer must be from 1 to 5")
    total = sum((a - 1) if i % 2 == 0 else (5 - a) for i, a in enumerate(answers))
    return total * 2.5


def band(mean: float) -> str:
    return next(word for floor, word in BANDS if mean >= floor)


def read_sus(path: Path) -> dict[str, float]:
    """{participant: score}. A row with a missing or invalid answer is reported, not guessed."""
    out: dict[str, float] = {}
    problems = []
    for row in csv.DictReader(path.open()):
        who = (row.get("participant") or "").strip()
        if not who:
            continue
        try:
            out[who] = sus_score([int(row[f"q{i}"]) for i in range(1, ITEMS + 1)])
        except (ValueError, KeyError, TypeError) as exc:
            problems.append(f"{who}: {exc}")
    if problems:
        raise ValueError("unusable SUS rows: " + "; ".join(problems))
    return out


def read_tasks(path: Path) -> dict[str, list[dict]]:
    """{task: rows}. `success` is 1, 0.5 or 0; rows with no task or no success are skipped."""
    out: dict[str, list[dict]] = {}
    for row in csv.DictReader(path.open()):
        task = (row.get("task") or "").strip()
        try:
            success = float(row["success"])
        except (KeyError, ValueError, TypeError):
            continue
        if not task or success not in (0.0, 0.5, 1.0):
            continue
        out.setdefault(task, []).append(
            {
                "success": success,
                "time_s": _num(row.get("time_s")),
                "wrong_turns": _num(row.get("wrong_turns")) or 0.0,
                "helped": _num(row.get("times_helped")) or 0.0,
            }
        )
    return out


def _num(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def summarise(scores: dict[str, float], tasks: dict[str, list[dict]]) -> dict:
    values = list(scores.values())
    mean = statistics.fmean(values) if values else None
    return {
        "participants": len(values),
        "sus": {
            **mean_ci(values),
            "band": band(mean) if mean is not None else None,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "stdev": round(statistics.stdev(values), 1) if len(values) > 1 else None,
            "small_group": len(values) < MIN_GROUP,
        },
        "tasks": {
            name: {
                "attempts": len(rows),
                "success_rate": round(statistics.fmean(r["success"] for r in rows), 3),
                "completed_fully": sum(r["success"] == 1 for r in rows),
                "median_time_s": _median([r["time_s"] for r in rows]),
                "wrong_turns_mean": round(statistics.fmean(r["wrong_turns"] for r in rows), 2),
                "needed_help": sum(r["helped"] > 0 for r in rows),
            }
            for name, rows in sorted(tasks.items())
        },
    }


def _median(values: list[float | None]) -> float | None:
    known = [v for v in values if v is not None]
    return round(statistics.median(known), 1) if known else None


def markdown(s: dict) -> str:
    sus = s["sus"]
    lines = [
        "# Usability results",
        "",
        f"{s['participants']} participants.",
        "",
    ]
    if sus["mean"] is None:
        lines.append("No SUS scores yet.")
    else:
        lines += [
            f"**SUS {sus['mean']} (95 % interval {sus['ci95'][0]}–{sus['ci95'][1]}; range "
            f'{sus["min"]}–{sus["max"]}), roughly "{sus["band"]}"** on the usual bands '
            "(about 68 is the average over many studies).",
        ]
        if sus["small_group"]:
            lines += [
                "",
                f"With fewer than {MIN_GROUP} participants this is a first impression, not a "
                "measurement: the interval is wide and one person moves the mean a long way.",
            ]
    lines += [
        "",
        "| task | attempts | success rate | fully completed | median time (s) | wrong turns | "
        "needed help |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, t in s["tasks"].items():
        lines.append(
            f"| {name} | {t['attempts']} | {t['success_rate']} | {t['completed_fully']} | "
            f"{t['median_time_s']} | {t['wrong_turns_mean']} | {t['needed_help']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sus", type=Path, required=True)
    ap.add_argument("--tasks", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    summary = summarise(read_sus(args.sus), read_tasks(args.tasks))
    text = markdown(summary)
    print(text)
    if args.out:
        args.out.write_text(text)


if __name__ == "__main__":
    main()
