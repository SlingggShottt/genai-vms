"""The retrieval ablation (P4-J6): the same questions asked with more and more of the system on.

    uv run --package vms-retrieval python ml/evaluation/retrieval/run_ablation.py \
        [--configs embed,embed+filters,+rerank,+jit] [--limit 50] [--jit-limit 12]

* `embed`           fast mode, no filters: image-text similarity and the heuristic plan alone
* `embed+filters`   the same, with the filters each query carries (camera, time range)
* `+rerank`         reason mode: a language model decomposes the query and rereads the best windows
* `+jit`            reason mode with picture checks: a vision model answers what the records cannot

Queries come from `queries.jsonl` (format and checks in `queries.py`); their places are on the
recording's own clock, which `meva_benchmark.calibrate` lines up with the wall clock (the stream
must have been recorded: see the README). Every number is a mean over queries, overall and for
explicit and implicit queries apart, with the stage latencies next to it. `+jit` is slow (a model
swap per candidate), so it runs on the first `--jit-limit` queries only and is compared with
`+rerank` on the same ones.

Writes `ml/evaluation/results/retrieval-ablation.json` and `.md`. It says nothing of the `hybrid`
and `cloud` profiles: those need provider keys; run it again under `VMS_LLM_PROFILE=hybrid` on the
retrieval service to get them, and pass `--profile-label hybrid`.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RESULTS = HERE.parent / "results"


def _load(name: str):  # noqa: ANN202
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


qs = _load("queries")
mt = _load("metrics")

CONFIGS: dict[str, dict[str, Any]] = {
    "embed": {"mode": "fast", "filters": False, "jit": False},
    "embed+filters": {"mode": "fast", "filters": True, "jit": False},
    "+rerank": {"mode": "reason", "filters": True, "jit": False},
    "+jit": {"mode": "reason", "filters": True, "jit": True},
}
SCORE_KEYS = ("R@1", "R@5", "R@10", "AP@10", "tIoU@0.3", "tIoU@0.5")

Search = Callable[[dict], Awaitable[dict]]


def payload(query: qs.Query, config: dict, top_k: int) -> dict:
    """The body of `POST /search` for one query under one configuration."""
    body: dict[str, Any] = {
        "query": query.text,
        "mode": config["mode"],
        "jit": config["jit"],
        "top_k": top_k,
    }
    if config["filters"] and query.cameras:
        body["filters"] = {"cameras": list(query.cameras)}
    return body


def places_of(query: qs.Query, origin: float | None) -> dict[str, list[mt.Window]]:
    """The relevant places by camera, on the epoch clock. `origin` is when the recording's own
    clock began; places given in absolute time need none."""
    out: dict[str, list[mt.Window]] = {}
    for seg in query.relevant:
        if seg.relative:
            if origin is None:
                raise ValueError(f"{query.id}: places on the recording's clock need an origin")
            window = (origin + seg.start, origin + seg.end)
        else:
            window = (seg.start, seg.end)
        out.setdefault(seg.camera, []).append(window)
    return out


def ranked_windows(body: dict) -> list[tuple[str, mt.Window]]:
    def ts(value: str) -> float:
        return datetime.fromisoformat(value).timestamp()

    return [(r["camera_id"], (ts(r["start_ts"]), ts(r["end_ts"]))) for r in body.get("results", [])]


CAMERA_SPREAD = 1e12  # seconds; far more than any recording, so cameras never overlap in time


def score(body: dict, places: dict[str, list[mt.Window]]) -> dict[str, float]:
    """The query's metrics. A window can only reach a place on its own camera: each camera is
    moved to its own stretch of the time axis, so the metrics, which know only windows, need no
    notion of a camera."""
    slot: dict[str, int] = {}

    def shift(camera: str, window: mt.Window) -> mt.Window:
        offset = slot.setdefault(camera, len(slot)) * CAMERA_SPREAD
        return (window[0] + offset, window[1] + offset)

    wanted = [shift(c, w) for c, ws in places.items() for w in ws]
    ranked = [shift(c, w) for c, w in ranked_windows(body)]
    return mt.query_scores(ranked, wanted)


async def run_config(
    search: Search,
    name: str,
    queries: list[qs.Query],
    origin: float | None,
    *,
    top_k: int = 10,
    log: Callable[[str], None] = print,
) -> dict:
    config = CONFIGS[name]
    rows = []
    for q in queries:
        started = time.perf_counter()
        try:
            body = await search(payload(q, config, top_k))
            error = None
        except Exception as exc:  # noqa: BLE001 - one failed search is a row, not the run
            body, error = {"results": [], "timings_ms": {}}, f"{type(exc).__name__}: {exc}"[:200]
        wall = time.perf_counter() - started
        scores = score(body, places_of(q, origin))
        rows.append(
            {
                "id": q.id,
                "kind": q.kind,
                "query": q.text,
                "wall_s": round(wall, 2),
                "timings_ms": body.get("timings_ms", {}),
                "notes": body.get("notes", []),
                "error": error,
                **scores,
            }
        )
        log(f"  {name:14} {q.id} R@1={scores['R@1']:.0f} R@10={scores['R@10']:.0f} {wall:5.1f}s")
    return {"config": name, "rows": rows, "summary": summarise(rows)}


def summarise(rows: list[dict]) -> dict:
    out: dict[str, Any] = {"n": len(rows), "errors": sum(bool(r["error"]) for r in rows)}
    out["overall"] = {k: mt.mean_of(rows, k) for k in SCORE_KEYS}
    for kind in qs.KINDS:
        sub = [r for r in rows if r["kind"] == kind]
        out[kind] = (
            {"n": len(sub), **{k: mt.mean_of(sub, k) for k in SCORE_KEYS}} if sub else {"n": 0}
        )
    out["wall_s_median"] = (
        round(sorted(r["wall_s"] for r in rows)[len(rows) // 2], 2) if rows else None
    )
    out["latency"] = mt.stage_latency([r["timings_ms"] for r in rows if r["timings_ms"]])
    return out


def markdown(report: dict) -> str:
    lines = [
        f"# Retrieval ablation — {report['profile']} profile, {report['finished_at']}",
        "",
        f"{report['n_queries']} queries ({report['implicit']} implicit) on camera "
        f"`{report['camera']}`; a result is relevant when it overlaps a relevant place by at "
        "least 2 s. R@k: a relevant window in the first k. mAP: average precision with the "
        "places as items (AP@10). tIoU@t: the first window's temporal IoU with a place is at "
        "least t.",
        "",
        "| configuration | queries | R@1 | R@5 | R@10 | mAP | tIoU@0.3 | tIoU@0.5 | median s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, data in report["configs"].items():
        o, n = data["summary"]["overall"], data["summary"]["n"]
        lines.append(
            f"| {name} | {n} | {o['R@1']:.2f} | {o['R@5']:.2f} | {o['R@10']:.2f} | "
            f"{o['AP@10']:.2f} | {o['tIoU@0.3']:.2f} | {o['tIoU@0.5']:.2f} | "
            f"{data['summary']['wall_s_median']} |"
        )
    lines += ["", "## Explicit and implicit queries apart", ""]
    lines += [
        "| configuration | kind | n | R@1 | R@5 | R@10 | mAP |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for name, data in report["configs"].items():
        for kind in qs.KINDS:
            s = data["summary"][kind]
            if s["n"]:
                lines.append(
                    f"| {name} | {kind} | {s['n']} | {s['R@1']:.2f} | {s['R@5']:.2f} | "
                    f"{s['R@10']:.2f} | {s['AP@10']:.2f} |"
                )
    lines += ["", "## Latency per stage (median / p95, ms)", ""]
    stages = sorted({s for d in report["configs"].values() for s in d["summary"]["latency"]})
    lines += ["| configuration | " + " | ".join(stages) + " |", "|---|" + "---:|" * len(stages)]
    for name, data in report["configs"].items():
        cells = []
        for stage in stages:
            v = data["summary"]["latency"].get(stage)
            cells.append(f"{v['median_ms']:.0f} / {v['p95_ms']:.0f}" if v else "–")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    if report.get("same_queries"):
        lines += ["", "## `+rerank` and `+jit` on the same queries", ""]
        lines += [
            "| configuration | n | R@1 | R@5 | R@10 | mAP |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for name, s in report["same_queries"].items():
            lines.append(
                f"| {name} | {s['n']} | {s['R@1']:.2f} | {s['R@5']:.2f} | {s['R@10']:.2f} | "
                f"{s['AP@10']:.2f} |"
            )
    errors = {
        n: d["summary"]["errors"] for n, d in report["configs"].items() if d["summary"]["errors"]
    }
    if errors:
        lines += ["", f"Searches that failed (counted as no result): {errors}"]
    return "\n".join(lines) + "\n"


async def main() -> None:
    import httpx

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--queries", type=Path, default=HERE / "queries.jsonl")
    ap.add_argument("--configs", default=",".join(CONFIGS))
    ap.add_argument("--limit", type=int, default=50, help="the first N queries (the baseline: 50)")
    ap.add_argument("--jit-limit", type=int, default=12, help="queries for +jit (it is slow)")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--retrieval-url", default="http://localhost:8010")
    ap.add_argument("--profile-label", default="local")
    ap.add_argument("--replay-start", default=str(ROOT / ".demo" / "last_replay_start"))
    ap.add_argument("--out", default=str(RESULTS / "retrieval-ablation"))
    args = ap.parse_args()

    queries = qs.load(args.queries)
    found = qs.problems(queries)
    if found:
        raise SystemExit("queries.jsonl has problems:\n" + "\n".join(found))
    queries = queries[: args.limit] if args.limit else queries
    mb = _load("meva_benchmark")
    manifest = json.loads((HERE / "meva_ex_manifest.json").read_text())
    camera = manifest["camera"]
    segments, tracks = await mb.fetch_recording(camera)
    if not segments:
        raise SystemExit(f"no recorded segments for camera {camera}: record the stream first")
    segments, tracks = mb.latest_recording(segments, tracks)
    first = segments[0][0]
    clips = mb.load_clips(manifest)
    cal = mb.calibrate(tracks, clips, first)
    prior = mb.replay_start(args.replay_start, first)
    if prior is not None:
        with_prior = mb.calibrate(tracks, clips, first, prior=(prior - 1.0, prior + 15.0))
        if abs(with_prior["t0"] - cal["t0"]) > 1.5:
            cal = {**with_prior, "disagreed_with": cal["t0"] - with_prior["t0"]}
    if cal["score"] < 1.5 * max(cal["runner_up_score"], 1.0):
        print("WARNING: the timeline alignment is weak; do not trust the numbers")
    origin = cal["t0"]

    report: dict[str, Any] = {
        "finished_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "profile": args.profile_label,
        "camera": camera,
        "n_queries": len(queries),
        "implicit": sum(q.kind == "implicit" for q in queries),
        "calibration": cal,
        "configs": {},
    }
    async with httpx.AsyncClient(base_url=args.retrieval_url, timeout=900) as client:

        async def search(body: dict) -> dict:
            r = await client.post("/search", json=body)
            r.raise_for_status()
            return r.json()

        await search({"query": "a person", "mode": "fast", "top_k": 3})  # warm up
        for name in args.configs.split(","):
            subset = queries[: args.jit_limit] if name == "+jit" else queries
            print(f"configuration {name} ({len(subset)} queries)")
            report["configs"][name] = await run_config(
                search, name, subset, origin, top_k=args.top_k
            )
    if "+jit" in report["configs"] and "+rerank" in report["configs"]:
        n = report["configs"]["+jit"]["summary"]["n"]
        same = report["configs"]["+rerank"]["rows"][:n]
        report["same_queries"] = {
            "+rerank": {"n": n, **{k: mt.mean_of(same, k) for k in SCORE_KEYS}},
            "+jit": {"n": n, **report["configs"]["+jit"]["summary"]["overall"]},
        }
    out = Path(args.out)
    out.with_suffix(".json").write_text(json.dumps(report, indent=1) + "\n")
    out.with_suffix(".md").write_text(markdown(report))
    print(f"wrote {out.with_suffix('.md')}")


if __name__ == "__main__":
    asyncio.run(main())
