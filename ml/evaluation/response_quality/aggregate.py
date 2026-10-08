"""Turn transcripts, judgements and report checks into numbers, and into the sheets people fill.

Nothing here calls a model. The judge's scores are the cheap signal; the 20 % human-verification
sheet is what says how far to trust them (`agreement`), and the report rubric form is where a person
scores incident reports on the four criteria.
"""

from __future__ import annotations

import csv
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # for `stats`

from stats import mean_ci  # noqa: E402

EXAMPLE_PROBLEM_PREFIX = "claims 4 october but the lookup covered"  # judge.py has the same string

RUBRIC = ("accuracy", "completeness", "causality", "actionability")


# ---- answers ------------------------------------------------------------------------------------


def citation_precision(rows: list[dict]) -> dict:
    """Of the citations the judge checked, the share that support their sentence: `strict` counts
    only "yes", `lenient` counts "partly" as half."""
    yes = partly = no = 0
    for r in rows:
        for c in (r.get("judgement") or {}).get("citations", []):
            yes += c["supports"] == "yes"
            partly += c["supports"] == "partly"
            no += c["supports"] == "no"
    total = yes + partly + no
    if not total:
        return {"checked": 0, "strict": None, "lenient": None}
    return {
        "checked": total,
        "strict": round(yes / total, 3),
        "lenient": round((yes + 0.5 * partly) / total, 3),
    }


def summarise_answers(rows: list[dict]) -> dict:
    """`rows`: {category, expect, transcript, judgement | None}."""
    answered = [r for r in rows if r["transcript"]["answer"] and not r["transcript"]["error"]]
    judged = [r for r in answered if r.get("judgement")]

    def scores(group: list[dict], key: str) -> list[float]:
        return [float(r["judgement"][key]) for r in group]

    by_category = {}
    for cat in sorted({r["category"] for r in rows}):
        g = [r for r in judged if r["category"] == cat]
        by_category[cat] = {
            "questions": sum(1 for r in rows if r["category"] == cat),
            "faithfulness": mean_ci(scores(g, "faithfulness")),
            "relevance": mean_ci(scores(g, "relevance")),
        }
    scope = {}
    for key in ("routed", "camera_scoped", "day_scoped"):
        known = [
            r["transcript"]["scope"][key]
            for r in answered
            if r["transcript"].get("scope", {}).get(key) is not None
        ]
        scope[key] = {
            "questions": len(known),
            "rate": round(sum(known) / len(known), 3) if known else None,
        }
    checks = [c for r in answered for c in r["transcript"].get("citation_check", [])]
    consistency = {
        "checked": len(checks),
        **{
            v: sum(c["verdict"] == v for c in checks)
            for v in ("consistent", "contradicted", "unclear")
        },
    }
    written = sum(len(r["transcript"].get("tags_written", [])) for r in answered)
    unknown = sum(len(r["transcript"].get("unknown_tags", [])) for r in answered)
    seconds = [r["transcript"]["seconds"] for r in answered if r["transcript"]["seconds"]]
    return {
        "questions": len(rows),
        "answered": len(answered),
        "errors": sum(1 for r in rows if r["transcript"]["error"]),
        "judged": len(judged),
        "judge_failures": len(answered) - len(judged),
        "faithfulness": mean_ci(scores(judged, "faithfulness")),
        "relevance": mean_ci(scores(judged, "relevance")),
        "faithfulness_adj": mean_ci(
            [
                float(r["judgement"].get("faithfulness_adj", r["judgement"]["faithfulness"]))
                for r in judged
            ]
        ),
        "relevance_adj": mean_ci(
            [
                float(r["judgement"].get("relevance_adj", r["judgement"]["relevance"]))
                for r in judged
            ]
        ),
        "judge_named_a_problem": sum(
            bool(r["judgement"].get("problem", "").strip()) for r in judged
        ),
        "faithfulness_4_or_5": round(
            sum(s >= 4 for s in scores(judged, "faithfulness")) / len(judged), 3
        )
        if judged
        else None,
        "citation_precision": citation_precision(judged),
        "citation_consistency": consistency,
        "problems_that_copy_the_prompt_example": sum(
            r["judgement"].get("problem", "").lower().startswith(EXAMPLE_PROBLEM_PREFIX)
            for r in judged
        ),
        "answers_that_cite": round(
            sum(
                1
                for r in answered
                if r["transcript"]["citations"] and not r["transcript"]["consulted_only"]
            )
            / len(answered),
            3,
        )
        if answered
        else None,
        "scope": scope,
        "tags_written": written,
        "tags_that_matched_no_record": unknown,
        "median_seconds": round(statistics.median(seconds), 2) if seconds else None,
        "by_category": by_category,
        "by_expectation": {
            e: {
                "questions": sum(1 for r in rows if r["expect"] == e),
                "faithfulness": mean_ci(
                    scores([r for r in judged if r["expect"] == e], "faithfulness")
                ),
                "relevance": mean_ci(scores([r for r in judged if r["expect"] == e], "relevance")),
            }
            for e in sorted({r["expect"] for r in rows})
        },
    }


# ---- incident reports ---------------------------------------------------------------------------


def summarise_reports(rows: list[dict]) -> dict:
    """`rows`: {incident_id, check, judgement | None}."""
    with_report = [r for r in rows if r["check"]["has_report"]]
    valid = [r for r in with_report if r["check"]["valid"]]
    judged = [r for r in valid if r.get("judgement")]
    out = {
        "incidents": len(rows),
        "with_a_report": len(with_report),
        "schema_valid": len(valid),
        "schema_valid_rate": round(len(valid) / len(with_report), 3) if with_report else None,
        "citations_not_in_index": sum(r["check"]["cited_not_in_index"] for r in valid),
        "citations_not_in_bundle": sum(r["check"]["cited_not_in_bundle"] or 0 for r in valid),
        "statements_left_out_for_citing_nothing": sum(r["check"]["claims_left_out"] for r in valid),
        "judged": len(judged),
    }
    for k in RUBRIC:
        out[k] = mean_ci([float(r["judgement"][k]) for r in judged])
    return out


# ---- the human sheets ---------------------------------------------------------------------------


def sample_for_humans(rows: list[dict], fraction: float = 0.2, seed: int = 7) -> list[dict]:
    """About `fraction` of the judged rows, at least one per category, chosen by a seeded draw so
    the
    sheet can be rebuilt. A person scores these without seeing the judge's scores first."""
    rng = random.Random(seed)  # noqa: S311 - sampling, not security
    judged = [r for r in rows if r.get("judgement")]
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in judged:
        by_cat[r["category"]].append(r)
    picked: list[dict] = []
    for cat in sorted(by_cat):
        group = sorted(by_cat[cat], key=lambda r: r["transcript"]["qid"])
        n = max(1, round(fraction * len(group)))
        picked += rng.sample(group, min(n, len(group)))
    return sorted(picked, key=lambda r: r["transcript"]["qid"])


SHEET_COLUMNS = [
    "qid", "category", "expect", "question", "answer", "records_the_assistant_had",
    "cited_records", "human_faithfulness_1to5", "human_relevance_1to5", "notes",
]  # fmt: skip
JUDGE_COLUMNS = ["qid", "judge_faithfulness", "judge_relevance"]  # kept apart: scored blind


def write_human_sheet(rows: list[dict], directory: Path) -> tuple[Path, Path]:
    """`human_verification.csv` (what a person fills, with no judge scores on it) and
    `human_verification_judge.csv` (the judge's scores for the same rows, for `agreement`)."""
    sheet, key = directory / "human_verification.csv", directory / "human_verification_judge.csv"
    with sheet.open("w", newline="") as f, key.open("w", newline="") as g:
        w, k = csv.writer(f), csv.writer(g)
        w.writerow(SHEET_COLUMNS)
        k.writerow(JUDGE_COLUMNS)
        for r in rows:
            t = r["transcript"]
            w.writerow(
                [
                    t["qid"], r["category"], r["expect"], t["question"], t["answer"],
                    " | ".join(
                        ((x.get("summary") or "") + " " + " ".join(x.get("lines") or []))[:400]
                        for x in t["tools"]
                    ),
                    " | ".join(
                        f"[{c['kind']}:{c['tag']}] {c.get('label', '')}"
                        for c in t["citations"]
                    ),
                    "", "", "",
                ]
            )  # fmt: skip
            k.writerow([t["qid"], r["judgement"]["faithfulness"], r["judgement"]["relevance"]])
    return sheet, key


def write_rubric_form(reports: list[dict], path: Path) -> Path:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["incident_id", "title", "summary"] + [f"human_{k}_1to5" for k in RUBRIC] + ["notes"]
        )
        for r in reports:
            w.writerow([r["incident_id"], r["title"], r["summary"], "", "", "", "", ""])
    return path


def quadratic_weighted_kappa(a: list[int], b: list[int], k: int = 5) -> float | None:
    """Agreement between two raters on a 1..k scale, weighted by squared distance (1 = perfect,
    0 = no better than chance). None if either rater used one value only and they differ in the
    expected disagreement being zero."""
    if len(a) != len(b) or not a:
        return None
    n = len(a)
    observed = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b, strict=True):
        observed[x - 1][y - 1] += 1
    ha = [sum(row) for row in observed]
    hb = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    num = den = 0.0
    for i in range(k):
        for j in range(k):
            w = (i - j) ** 2 / (k - 1) ** 2
            num += w * observed[i][j]
            den += w * ha[i] * hb[j] / n
    return None if den == 0 else round(1 - num / den, 3)


def agreement(human: list[int], judge: list[int]) -> dict:
    """How the judge compares with a person on the same items."""
    if not human or len(human) != len(judge):
        return {"n": 0}
    diffs = [abs(h - j) for h, j in zip(human, judge, strict=True)]
    return {
        "n": len(human),
        "exact": round(sum(d == 0 for d in diffs) / len(diffs), 3),
        "within_1": round(sum(d <= 1 for d in diffs) / len(diffs), 3),
        "mean_abs_error": round(statistics.fmean(diffs), 3),
        "human_mean": round(statistics.fmean(human), 3),
        "judge_mean": round(statistics.fmean(judge), 3),
        "quadratic_kappa": quadratic_weighted_kappa(human, judge),
    }


def read_filled_sheet(sheet: Path, key: Path) -> dict:
    """Agreement per criterion from a filled `human_verification.csv` and its judge key. Rows a
    person left blank are ignored."""
    judge = {r["qid"]: r for r in csv.DictReader(key.open())}
    human_f, judge_f, human_r, judge_r = [], [], [], []
    for r in csv.DictReader(sheet.open()):
        j = judge.get(r["qid"])
        if not j:
            continue
        for col, hs, js, jcol in (
            ("human_faithfulness_1to5", human_f, judge_f, "judge_faithfulness"),
            ("human_relevance_1to5", human_r, judge_r, "judge_relevance"),
        ):
            value = (r.get(col) or "").strip()
            if value.isdigit() and 1 <= int(value) <= 5:
                hs.append(int(value))
                js.append(int(j[jcol]))
    return {"faithfulness": agreement(human_f, judge_f), "relevance": agreement(human_r, judge_r)}


def read_filled_rubric(path: Path) -> dict:
    """Mean human score per rubric criterion from a filled form (blank rows ignored)."""
    cols: dict[str, list[int]] = {k: [] for k in RUBRIC}
    for r in csv.DictReader(path.open()):
        for k in RUBRIC:
            v = (r.get(f"human_{k}_1to5") or "").strip()
            if v.isdigit() and 1 <= int(v) <= 5:
                cols[k].append(int(v))
    return {k: mean_ci([float(x) for x in v]) for k, v in cols.items()}
