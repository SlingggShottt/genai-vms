"""Response-quality evaluation (P7-J4): are the assistant's answers and the incident reports
faithful to the records they were built from?

    uv run python ml/evaluation/response_quality/run.py collect --run runs/baseline
    uv run python ml/evaluation/response_quality/run.py judge   --run runs/baseline
    uv run python ml/evaluation/response_quality/run.py summary --run runs/baseline \
        [--compare runs/after]

`collect` asks every question through the API (a fresh session each) and keeps what the assistant
answered, looked up and cited. `judge` scores each answer and each stored incident report with the
gateway's `eval_judge` task, a different model family from the generator (config/models.yaml), and
runs the checks that need no model. `summary` writes the numbers (`results/response-quality.*`)
and the sheets a person fills: a 20 % verification sample of the answers, with the judge's scores
kept apart, and a rubric form for the incident reports. Run `collect` and `judge` as separate
steps: the assistant and the judge are different models and the 4 GB GPU holds one.

What this does not do: say whether an answer is true of the world (only whether it follows from
the records the assistant had; those can themselves be wrong), or replace the human sheets. A 3B
judge is a signal; `summary --filled-sheet` reports how far it agrees with a person once the
sheet is scored.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # for the sibling modules
sys.path.insert(0, str(HERE.parent))  # for `stats`

import aggregate  # noqa: E402
import collect  # noqa: E402
import judge  # noqa: E402
import questions  # noqa: E402
from vms_common.contracts.reasoning import IncidentReportV1  # noqa: E402

RESULTS = HERE.parent / "results"


def dump(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows))


def load(path: Path) -> list[dict]:
    return (
        [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []
    )


async def db_rows(sql: str, **params) -> list[dict]:
    from sqlalchemy import text
    from vms_common.config import DatabaseSettings
    from vms_db.session import create_engine

    engine = create_engine(DatabaseSettings())
    try:
        async with engine.connect() as c:
            return [dict(r._mapping) for r in (await c.execute(text(sql), params)).all()]
    finally:
        await engine.dispose()


async def scope() -> tuple[list[str], list, list[str]]:
    """The cameras, days and event types that have verified events: what questions can be about."""
    rows = await db_rows(
        "select camera_id, (start_ts at time zone 'UTC')::date d, event_type from events.events "
        "where status = 'verified'"
    )
    return (
        sorted({r["camera_id"] for r in rows}),
        sorted({r["d"] for r in rows}),
        sorted({r["event_type"] for r in rows}),
    )


# ---- collect ------------------------------------------------------------------------------------


async def cmd_collect(args: argparse.Namespace) -> None:
    from dotenv import dotenv_values

    env = dotenv_values(HERE.parents[2] / ".env")
    cams, days, types = await scope()
    qs = questions.build_questions(cams, days, types, seed=args.seed)
    if args.limit:
        qs = qs[: args.limit]
    run = Path(args.run)
    await asyncio.to_thread(run.mkdir, parents=True, exist_ok=True)
    dump(run / "questions.jsonl", [q.as_json() for q in qs])
    assistant = collect.Assistant(args.api, env["VMS_ADMIN_EMAIL"], env["VMS_ADMIN_PASSWORD"])
    out = []
    try:
        for i, q in enumerate(qs, 1):
            t = await asyncio.to_thread(assistant.ask, q.qid, q.category, q.text)
            row = t.as_json() | {
                "expect": q.expect,
                "camera": q.camera,
                "day": q.day,
                "tool": q.tool,
            }
            out.append(row)
            print(
                f"  {i}/{len(qs)} {q.qid} {t.seconds}s {'ERROR ' + t.error if t.error else ''}",
                flush=True,
            )
    finally:
        assistant.close()
    dump(run / "transcripts.jsonl", out)
    print(f"wrote {run / 'transcripts.jsonl'} ({len(out)} transcripts)")


# ---- judge --------------------------------------------------------------------------------------


async def cmd_judge(args: argparse.Namespace) -> None:
    from redis.asyncio import Redis
    from vms_common.config import LLMSettings
    from vms_common.llm import LLMGateway

    run = Path(args.run)
    transcripts = load(run / "transcripts.jsonl")
    if not transcripts:
        raise SystemExit(f"{run}/transcripts.jsonl is empty: run `collect` first")
    redis = Redis.from_url(args.redis_url, decode_responses=True)
    await redis.flushdb()  # a cached verdict would hide a judge that has changed
    gateway = LLMGateway.from_settings(LLMSettings(), redis=redis)
    try:
        answers = []
        for i, t in enumerate(transcripts, 1):
            t["tags_written"] = judge.tags_written(t["answer"])
            t["scope"] = judge.scope_check(t)
            verdict = None
            if t["answer"] and not t["error"]:
                v = await judge.judge_answer(gateway, t, t["expect"])
                verdict = v.model_dump() if v else None
            answers.append({"qid": t["qid"], "category": t["category"], "expect": t["expect"],
                            "transcript": t, "judgement": verdict})  # fmt: skip
            scores = verdict and (verdict["faithfulness"], verdict["relevance"])
            print(f"  answer {i}/{len(transcripts)} {t['qid']} {scores}", flush=True)
        dump(run / "answers.jsonl", answers)

        incidents = await db_rows(
            "select id::text as incident_id, title, status, report, evidence "
            "from reasoning.incidents where status <> 'generating' order by created_at"
        )
        reports = []
        for i, inc in enumerate(incidents, 1):
            texts = judge.evidence_texts(inc["evidence"])
            check = judge.check_report(inc["report"], texts)
            verdict = None
            if check["valid"]:
                report = IncidentReportV1.model_validate(inc["report"])
                v = await judge.judge_report(gateway, report, texts)
                verdict = v.model_dump() if v else None
            reports.append({"incident_id": inc["incident_id"], "title": inc["title"],
                            "summary": (inc["report"] or {}).get("summary", ""),
                            "check": check, "judgement": verdict})  # fmt: skip
            print(
                f"  report {i}/{len(incidents)} {inc['incident_id'][:8]} valid={check['valid']}",
                flush=True,
            )
        dump(run / "reports.jsonl", reports)
    finally:
        await gateway.aclose()
        await redis.flushdb()
        await redis.aclose()


# ---- summary ------------------------------------------------------------------------------------


def cell(d: dict | None) -> str:
    if not d or d.get("mean") is None:
        return "–"
    return f"{d['mean']} ({d['ci95'][0]}–{d['ci95'][1]}, n={d['n']})"


def run_summary(run: Path) -> dict:
    answers, reports = load(run / "answers.jsonl"), load(run / "reports.jsonl")
    return {
        "answers": aggregate.summarise_answers(answers),
        "reports": aggregate.summarise_reports(reports),
    }


def _row(label: str, fn, runs: dict[str, dict], names: list[str], part: str) -> str:
    return f"| {label} | " + " | ".join(fn(runs[n][part]) for n in names) + " |"


def _precision(s: dict) -> str:
    c = s["citation_precision"]
    return f"{c['strict']} / {c['lenient']} (n={c['checked']})"


def _rate(key: str):
    def fn(s: dict) -> str:
        v = s["scope"][key]
        return f"{v['rate']} (n={v['questions']})"

    return fn


def _group_rows(groups: dict) -> list[str]:
    return [
        f"| {name} | {v['questions']} | {cell(v['faithfulness'])} | {cell(v['relevance'])} |"
        for name, v in groups.items()
    ]


INTRO = (
    "Generator: `qwen2.5:3b` (assistant, reports). Judge: `llama3.2:3b` through the gateway's "
    "`eval_judge` task, a different family from the generator. It is a 3B judge, so read "
    "its scores as a signal, and the human-agreement figures below as how far to trust it. "
    "The judge sees only the records the assistant had: it measures whether an answer follows "
    "from them, not whether they are right."
)


def markdown(runs: dict[str, dict], when: str, filled: dict | None) -> str:
    names = list(runs)
    head = " | ".join(names)
    table = [f"| | {head} |", "|---|" + "---|" * len(names)]
    lines = [
        "# Response quality: assistant answers and incident reports",
        "",
        f"**Run {when}**, local profile. {INTRO}",
        "",
        "## Assistant answers",
        "",
        *table,
    ]
    answer_rows = [
        ("questions asked / answered", lambda s: f"{s['questions']} / {s['answered']}"),
        ("judged (judge failures)", lambda s: f"{s['judged']} ({s['judge_failures']})"),
        ("faithfulness 1–5", lambda s: cell(s["faithfulness"])),
        ("faithfulness 4 or 5", lambda s: str(s["faithfulness_4_or_5"])),
        ("relevance 1–5", lambda s: cell(s["relevance"])),
        ("first lookup was the right tool", _rate("routed")),
        ("a lookup used the camera asked about", _rate("camera_scoped")),
        ("a lookup used the day asked about", _rate("day_scoped")),
        ("citation precision, strict / lenient", _precision),
        ("answers that cite a record", lambda s: str(s["answers_that_cite"])),
        (
            "tags written that match no record",
            lambda s: f"{s['tags_that_matched_no_record']} of {s['tags_written']}",
        ),
        ("median seconds per answer", lambda s: str(s["median_seconds"])),
    ]
    lines += [_row(label, fn, runs, names, "answers") for label, fn in answer_rows]
    last = runs[names[-1]]["answers"]
    lines += [
        "",
        f"### By category ({names[-1]})",
        "",
        "| category | questions | faithfulness | relevance |",
        "|---|---|---|---|",
        *_group_rows(last["by_category"]),
        "",
        "| expected behaviour | questions | faithfulness | relevance |",
        "|---|---|---|---|",
        *_group_rows(last["by_expectation"]),
        "",
        "## Incident reports",
        "",
        *table,
    ]
    report_rows = [
        ("incidents / with a report", lambda s: f"{s['incidents']} / {s['with_a_report']}"),
        (
            "validate against `incident.v1`",
            lambda s: f"{s['schema_valid']} ({s['schema_valid_rate']})",
        ),
        ("cited ids missing from the report's index", lambda s: str(s["citations_not_in_index"])),
        ("cited ids missing from the evidence", lambda s: str(s["citations_not_in_bundle"])),
        (
            "statements dropped for citing nothing",
            lambda s: str(s["statements_left_out_for_citing_nothing"]),
        ),
        ("judged", lambda s: str(s["judged"])),
        *((f"{k} 1–5 (judge)", lambda s, k=k: cell(s[k])) for k in aggregate.RUBRIC),
    ]
    lines += [_row(label, fn, runs, names, "reports") for label, fn in report_rows]
    lines += ["", "## Judge against a person", ""]
    if filled:
        lines.append(json.dumps(filled, indent=1))
    else:
        lines.append(
            "Not measured yet: `human_verification.csv` (20 % of the answers) and the report "
            "rubric form are written next to the run. Once a person has filled them, "
            "`summary --filled-sheet ... --filled-rubric ...` adds the agreement and the human "
            "rubric means."
        )
    return "\n".join(lines) + "\n"


async def cmd_summary(args: argparse.Namespace) -> None:
    runs = {}
    for r in [*(args.compare or []), args.run]:
        runs[Path(r).name] = run_summary(Path(r))
    run = Path(args.run)
    answers, reports = load(run / "answers.jsonl"), load(run / "reports.jsonl")
    sample = aggregate.sample_for_humans(answers)
    sheet, key = aggregate.write_human_sheet(sample, run)
    form = aggregate.write_rubric_form(reports, run / "report_rubric_form.csv")
    filled = None
    if args.filled_sheet:
        filled = aggregate.read_filled_sheet(Path(args.filled_sheet), key)
    if args.filled_rubric:
        filled = (filled or {}) | {
            "human_rubric": aggregate.read_filled_rubric(Path(args.filled_rubric))
        }
    when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "response-quality"
    out.with_suffix(".json").write_text(
        json.dumps({"when": when, "runs": runs, "human": filled}, indent=1) + "\n"
    )
    out.with_suffix(".md").write_text(markdown(runs, when, filled))
    print(f"wrote {out}.md/.json, {sheet.name} ({len(sample)} answers), {key.name}, {form.name}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--run", required=True)
    c.add_argument("--api", default="http://localhost:8000/api/v1")
    c.add_argument("--seed", type=int, default=7)
    c.add_argument("--limit", type=int, default=0, help="only the first N questions (a smoke test)")
    j = sub.add_parser("judge")
    j.add_argument("--run", required=True)
    j.add_argument("--redis-url", default="redis://localhost:6379/9", help="scratch db")
    s = sub.add_parser("summary")
    s.add_argument("--run", required=True)
    s.add_argument(
        "--compare", action="append", help="an earlier run directory to show beside this one"
    )
    s.add_argument("--filled-sheet", help="a filled human_verification.csv")
    s.add_argument("--filled-rubric", help="a filled report_rubric_form.csv")
    args = ap.parse_args()
    asyncio.run(
        {"collect": cmd_collect, "judge": cmd_judge, "summary": cmd_summary}[args.cmd](args)
    )


if __name__ == "__main__":
    main()
