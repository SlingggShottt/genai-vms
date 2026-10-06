"""Retrieval benchmark on real labels: MEVA activity clips recorded as one camera.

    uv run --package vms-retrieval python ml/evaluation/retrieval/meva_benchmark.py \
        [--retrieval-url http://localhost:8010] [--modes fast,reason] [--top-k 10]

What it measures: for each of 36 plain-language queries ("a person gets into a car"), do the top-k
windows of footage that search returns land on a clip of that activity? The clips come from the
MEVA examples set, joined into one stream by `build_meva_stream.py` and recorded through the normal
pipeline as camera `meva-ex`; the ground truth is the clip's label and its place on the stream's
timeline (`meva_ex_manifest.json`). No human labelled anything for this benchmark.

How the timeline is lined up with wall-clock time: ingestion joins a stream late, so when the
stream began is not known exactly. The stream has a black leader and a black gap after every clip,
and perception finds nothing in black frames, so this slides the manifest over the recorded tracks
and keeps the offset where tracks fall inside clips and not inside gaps (`calibrate`). The score
and the runner-up are in the report; a weak margin means the numbers should not be trusted.

A result window counts as relevant to a query when it overlaps a clip of that activity by at least
2 s. Reported per query and averaged over queries (macro): hit@k (any relevant window in the top
k), precision@k, the share of the activity's clips reached, and the reciprocal rank of the first
relevant window, next to what picking windows at random would score. Writes
`ml/evaluation/results/meva-retrieval-benchmark.json` and a Markdown table next to it.

What it does not do: judge answer quality, test several cameras or long footage (the stream is 36
minutes of short staged clips with black gaps, far easier to separate than a day of one camera),
or say how search copes with queries that are not a clean activity name.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import yaml

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"
MIN_OVERLAP_S = 2.0
KS = (1, 3, 5, 10)


@dataclass(frozen=True)
class Clip:
    clip: str
    activity: str
    start_s: float
    end_s: float


def overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def load_clips(manifest: dict) -> list[Clip]:
    return [Clip(c["clip"], c["activity"], c["start_s"], c["end_s"]) for c in manifest["clips"]]


def check_queries(queries: list[dict], clips: list[Clip]) -> None:
    """Every labelled activity has exactly one query, and no query is for an unknown activity."""
    wanted = {c.activity for c in clips}
    asked = [q["activity"] for q in queries]
    missing = sorted(wanted - set(asked))
    unknown = sorted(set(asked) - wanted)
    dupes = sorted({a for a in asked if asked.count(a) > 1})
    if missing or unknown or dupes:
        raise SystemExit(
            f"queries do not match the labels: missing={missing} unknown={unknown} dupes={dupes}"
        )


def calibrate(
    tracks: list[tuple[float, float]],
    clips: list[Clip],
    first_segment_ts: float,
    *,
    latest_start_s: float = 90.0,
    step_s: float = 0.5,
) -> dict:
    """Wall-clock time (epoch seconds) at which the stream began.

    `tracks` are (first, last) epoch seconds of every recorded track. A candidate start `t0` is
    scored by how much track presence falls inside clips (+1 per half-second bin) against inside
    leader or gaps (-1). The stream began before ingestion recorded its first segment, by at most
    `latest_start_s`, so only those candidates are tried.
    """
    if not tracks or not clips:
        raise ValueError("no tracks or no clips to calibrate on")
    lo = min(t[0] for t in tracks)
    hi = max(t[1] for t in tracks)
    edges = np.arange(lo, hi + step_s, step_s)
    present = np.zeros(len(edges), dtype=bool)
    for a, b in tracks:
        present[int((a - lo) / step_s) : int((b - lo) / step_s) + 1] = True
    centres = edges + step_s / 2
    starts = np.array([c.start_s for c in clips])
    ends = np.array([c.end_s for c in clips])
    order = np.argsort(starts)
    starts, ends = starts[order], ends[order]

    candidates = np.arange(first_segment_ts - latest_start_s, first_segment_ts + 2.0, step_s)
    scores = np.empty(len(candidates))
    for i, t0 in enumerate(candidates):
        s = centres - t0
        idx = np.searchsorted(starts, s, side="right") - 1
        inside = (idx >= 0) & (s < ends[np.clip(idx, 0, None)])
        scores[i] = float(np.sum(np.where(present, np.where(inside, 1, -1), 0)))
    best = int(np.argmax(scores))
    far = np.abs(candidates - candidates[best]) > 3.0
    runner_up = float(scores[far].max()) if far.any() else float("nan")
    s = centres - candidates[best]
    idx = np.searchsorted(starts, s, side="right") - 1
    inside = (idx >= 0) & (s < ends[np.clip(idx, 0, None)])
    return {
        "t0": float(candidates[best]),
        "score": float(scores[best]),
        "runner_up_score": runner_up,
        "late_join_s": float(first_segment_ts - candidates[best]),
        "presence_inside_clips": float(np.sum(present & inside) / max(1, np.sum(present))),
    }


def relevant(window: tuple[float, float], spans: list[tuple[float, float]]) -> bool:
    return any(overlap(*window, a, b) >= MIN_OVERLAP_S for a, b in spans)


def query_metrics(
    ranked: list[tuple[float, float]],
    spans: list[tuple[float, float]],
    ks: tuple[int, ...] = KS,
) -> dict:
    """Metrics of one query: `ranked` windows (epoch seconds) best first, `spans` = the activity's
    clips on the same clock."""
    flags = [relevant(w, spans) for w in ranked]
    out: dict = {"first_relevant_rank": next((i + 1 for i, f in enumerate(flags) if f), None)}
    out["rr"] = 1.0 / out["first_relevant_rank"] if out["first_relevant_rank"] else 0.0
    for k in ks:
        top = flags[:k]
        out[f"hit@{k}"] = float(any(top))
        out[f"p@{k}"] = sum(top) / k
        reached = sum(any(overlap(*w, a, b) >= MIN_OVERLAP_S for w in ranked[:k]) for a, b in spans)
        out[f"clips@{k}"] = reached / len(spans)
    return out


def random_baseline(n_windows: int, n_relevant: int, ks: tuple[int, ...] = KS) -> dict:
    """What picking k windows at random out of all would score."""
    out = {}
    for k in ks:
        kk = min(k, n_windows)
        miss = (
            math.comb(n_windows - n_relevant, kk) / math.comb(n_windows, kk)
            if n_windows >= kk
            else 0.0
        )
        out[f"hit@{k}"] = 1.0 - miss
        out[f"p@{k}"] = n_relevant / n_windows if n_windows else 0.0
    return out


def mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 3) if values else float("nan")


def aggregate(rows: list[dict], keys: list[str]) -> dict:
    return {k: mean([r[k] for r in rows if r.get(k) is not None]) for k in keys}


def ts(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


async def fetch_recording(
    camera: str,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    from sqlalchemy import text
    from vms_common.config import DatabaseSettings
    from vms_db.session import create_engine

    engine = create_engine(DatabaseSettings())
    try:
        async with engine.connect() as c:
            segs = (
                await c.execute(
                    text(
                        "select start_ts, end_ts from media.segments "
                        "where camera_id = :c order by start_ts"
                    ),
                    {"c": camera},
                )
            ).all()
            trk = (
                await c.execute(
                    text("select first_ts, last_ts from vision.tracks where camera_id = :c"),
                    {"c": camera},
                )
            ).all()
    finally:
        await engine.dispose()
    return (
        [(a.timestamp(), b.timestamp()) for a, b in segs],
        [(a.timestamp(), b.timestamp()) for a, b in trk],
    )


async def run_mode(
    client: httpx.AsyncClient,
    mode: str,
    queries: list[dict],
    clips: list[Clip],
    t0: float,
    camera: str,
    top_k: int,
    n_windows: int,
    windows: list[tuple[float, float]],
) -> dict:
    rows = []
    for q in queries:
        spans = [(t0 + c.start_s, t0 + c.end_s) for c in clips if c.activity == q["activity"]]
        started = time.perf_counter()
        r = await client.post(
            "/search",
            json={
                "query": q["query"],
                "mode": mode,
                "top_k": top_k,
                "filters": {"cameras": [camera]},
            },
        )
        r.raise_for_status()
        body = r.json()
        wall = time.perf_counter() - started
        ranked = [(ts(x["start_ts"]), ts(x["end_ts"])) for x in body["results"]]
        m = query_metrics(ranked, spans)
        n_rel = sum(relevant(w, spans) for w in windows)
        base = random_baseline(n_windows, n_rel)
        on_any_clip = [
            relevant(w, [(t0 + c.start_s, t0 + c.end_s) for c in clips]) for w in ranked[:top_k]
        ]
        rows.append(
            {
                "activity": q["activity"],
                "family": q["family"],
                "query": q["query"],
                "n_clips": len(spans),
                "n_relevant_windows": n_rel,
                "n_results": len(ranked),
                "wall_s": round(wall, 2),
                "notes": body.get("notes", []),
                "on_any_clip": sum(on_any_clip) / len(on_any_clip) if on_any_clip else 0.0,
                "baseline": base,
                **m,
            }
        )
        print(
            f"  {mode:6} {q['activity']:24} first relevant rank {m['first_relevant_rank']}",
            flush=True,
        )
    return {"rows": rows}


def summarise(rows: list[dict]) -> dict:
    keys = [f"{m}@{k}" for k in KS for m in ("hit", "p", "clips")] + ["rr", "on_any_clip"]
    overall = aggregate(rows, keys)
    overall["baseline"] = {
        f"{m}@{k}": mean([r["baseline"][f"{m}@{k}"] for r in rows])
        for k in KS
        for m in ("hit", "p")
    }
    overall["wall_s_median"] = round(statistics.median(r["wall_s"] for r in rows), 2)
    overall["queries_with_a_degradation_note"] = sum(bool(r["notes"]) for r in rows)
    fam = {}
    for f in sorted({r["family"] for r in rows}):
        sub = [r for r in rows if r["family"] == f]
        fam[f] = {"n": len(sub), **aggregate(sub, ["hit@1", "hit@5", "hit@10", "p@5", "rr"])}
    return {"overall": overall, "families": fam}


INTRO = (
    "How to read it: a result window is relevant when it overlaps a clip of the queried activity "
    "by at least 2 s. Numbers are averaged over the queries (one per activity). *Random* is what "
    "k random windows would score. The stream is short staged clips separated by black gaps, which "
    "is far easier to separate than a day of one camera, so these numbers are a ceiling for hard "
    "footage, not a promise."
)


def table_row(label: str, values: dict, metric: str) -> str:
    cells = " | ".join(str(values[f"{metric}@{k}"]) for k in KS)
    return f"| {label} | {cells} |"


def markdown(report: dict) -> str:
    cal = report["calibration"]
    lines = [
        "# Retrieval benchmark on real labels (MEVA activity clips)",
        "",
        f"**Run {report['finished_at']}**, local profile, camera `{report['camera']}`: "
        f"{report['n_clips']} labelled clips of {report['n_activities']} activities joined into a "
        f"{report['stream_minutes']:.0f}-minute stream, {report['n_windows']} recorded windows. "
        "Produced by `ml/evaluation/retrieval/meva_benchmark.py`; the labels are the MEVA clip "
        "names, nobody annotated anything.",
        "",
        INTRO,
        "",
        f"Timeline alignment: the stream start was found at an offset scoring {cal['score']:.0f} "
        f"(runner-up {cal['runner_up_score']:.0f}); "
        f"{cal['presence_inside_clips'] * 100:.0f}% of tracked time lies inside clips; "
        f"ingestion joined {cal['late_join_s']:.1f} s late.",
        "",
    ]
    for mode, data in report["modes"].items():
        o = data["summary"]["overall"]
        b = o["baseline"]
        lines += [
            f"## {mode} mode",
            "",
            "| | @1 | @3 | @5 | @10 |",
            "|---|---|---|---|---|",
            table_row("hit (any relevant window)", o, "hit"),
            table_row("random hit", b, "hit"),
            table_row("precision", o, "p"),
            table_row("random precision", b, "p"),
            table_row("share of the activity's clips reached", o, "clips"),
            "",
            f"Mean reciprocal rank {o['rr']}; {o['on_any_clip'] * 100:.0f}% of returned windows "
            f"lie on some clip rather than black; median {o['wall_s_median']} s per query; "
            f"{o['queries_with_a_degradation_note']} of {len(data['rows'])} queries carried a "
            "degradation note.",
            "",
            "| family | queries | hit@1 | hit@5 | hit@10 | precision@5 | MRR |",
            "|---|---|---|---|---|---|---|",
        ]
        for f, v in data["summary"]["families"].items():
            cells = " | ".join(str(v[k]) for k in ("hit@1", "hit@5", "hit@10", "p@5", "rr"))
            lines.append(f"| {f} | {v['n']} | {cells} |")
        lines += [
            "",
            "| activity | clips | first relevant rank | hit@10 | precision@10 |",
            "|---|---|---|---|---|",
        ]
        by_rank = sorted(
            data["rows"],
            key=lambda r: (r["first_relevant_rank"] is None, r["first_relevant_rank"] or 0),
        )
        for r in by_rank:
            rank = r["first_relevant_rank"] if r["first_relevant_rank"] else "-"
            lines.append(
                f"| {r['activity']} | {r['n_clips']} | {rank} | "
                f"{r['hit@10']:.0f} | {r['p@10']:.1f} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrieval-url", default="http://localhost:8010")
    ap.add_argument("--modes", default="fast,reason")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0, help="only the first N queries (a smoke test)")
    ap.add_argument("--out", default=str(RESULTS / "meva-retrieval-benchmark"))
    args = ap.parse_args()

    manifest = json.loads((HERE / "meva_ex_manifest.json").read_text())
    clips = load_clips(manifest)
    queries = yaml.safe_load((HERE / "meva_queries.yaml").read_text())["queries"]
    check_queries(queries, clips)
    if args.limit:
        queries = queries[: args.limit]
    camera = manifest["camera"]

    windows_ts, tracks = await fetch_recording(camera)
    if not windows_ts:
        raise SystemExit(f"no recorded segments for camera {camera}: record the stream first")
    cal = calibrate(tracks, clips, windows_ts[0][0])
    print(f"calibration: {cal}")
    if cal["score"] < 1.5 * max(cal["runner_up_score"], 1.0):
        print("WARNING: the timeline alignment is weak; do not trust the numbers")
    t0 = cal["t0"]

    report: dict = {
        "finished_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "camera": camera,
        "n_clips": len(clips),
        "n_activities": len({c.activity for c in clips}),
        "stream_minutes": manifest["duration_s"] / 60,
        "n_windows": len(windows_ts),
        "calibration": cal,
        "modes": {},
    }
    async with httpx.AsyncClient(base_url=args.retrieval_url, timeout=300) as client:
        await client.post(
            "/search", json={"query": "a person", "mode": "fast", "top_k": 3}
        )  # warm up
        for mode in args.modes.split(","):
            print(f"mode {mode}")
            data = await run_mode(
                client, mode, queries, clips, t0, camera, args.top_k, len(windows_ts), windows_ts
            )
            data["summary"] = summarise(data["rows"])
            report["modes"][mode] = data
    out = Path(args.out)
    out.with_suffix(".json").write_text(json.dumps(report, indent=1) + "\n")
    out.with_suffix(".md").write_text(markdown(report))
    print(f"wrote {out.with_suffix('.md')}")


if __name__ == "__main__":
    asyncio.run(main())
