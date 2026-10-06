"""Latency and throughput of the running stack (design §13 `latency/`, P7-D4): what an operator
waits for, measured through the real services rather than on a model in isolation.

    uv run --package vms-retrieval python ml/evaluation/latency/measure.py \
        [--retrieval-url http://localhost:8010] [--fast 30] [--reason 4] [--assistant 4]

It drives `retrieval` over HTTP (searches, image search, grounding, the assistant) and reads the
rest from Postgres (how long segments took to become searchable, how long reasoning jobs and
daily reports took). It needs the stack up, footage indexed, and the language model reachable.
Writes `ml/evaluation/results/p7-latency.json` and a Markdown table next to it.

What it does not do: vary the number of cameras (the camera simulator drives that; this measures
the stack that is running), measure concurrent users, or judge answer quality.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
from sqlalchemy import text
from vms_common.config import DatabaseSettings
from vms_db.session import create_engine

SUBJECTS = ["a person", "a man", "a woman", "someone", "a pedestrian"]
DETAILS = [
    "in a red top",
    "carrying a backpack",
    "with a blue bag",
    "in a dark jacket",
    "wearing orange",
    "near the service door",
    "in the plaza",
    "holding a phone",
    "with a handbag",
    "in white clothes",
    "walking past a red box",
    "in the restricted yard",
]


def fresh_queries(n: int, seed: int) -> list[str]:
    """`n` distinct queries that differ from earlier runs. The gateway caches query plans and
    reranks for an hour (design §11), so repeating a query would time the cache, not the work."""
    rng = random.Random(seed)  # noqa: S311 - shuffling queries, not a secret
    combos = [f"{s} {d}" for s in SUBJECTS for d in DETAILS]
    rng.shuffle(combos)
    return combos[:n]


ASSISTANT_QUESTIONS = [
    "Were there any serious incidents on cam01 today?",
    "How many people were on cam01 at the busiest time today?",
    "What happened on cam01 in the last 24 hours?",
    "Find a person in a red top",
]


def pct(values: list[float], q: float) -> float:
    return float(np.percentile(values, q)) if values else float("nan")


def summarize(values: list[float]) -> dict:
    return {
        "n": len(values),
        "p50": round(pct(values, 50), 3),
        "p95": round(pct(values, 95), 3),
        "min": round(min(values), 3) if values else None,
        "max": round(max(values), 3) if values else None,
        "mean": round(statistics.fmean(values), 3) if values else None,
    }


async def search(client: httpx.AsyncClient, query: str, mode: str) -> dict:
    t = time.perf_counter()
    r = await client.post("/search", json={"query": query, "mode": mode, "top_k": 12})
    r.raise_for_status()
    body = r.json()
    body["_wall_s"] = time.perf_counter() - t
    return body


async def measure_search(client: httpx.AsyncClient, queries: list[str], mode: str, n: int) -> dict:
    await search(client, "a person", "fast")  # warm the encoder and the connections
    walls: list[float] = []
    stages: dict[str, list[float]] = {}
    degraded = 0
    for i in range(n):
        body = await search(
            client, queries[i % len(queries)] + ("" if i < len(queries) else " "), mode
        )
        walls.append(body["_wall_s"])
        degraded += bool(body["notes"])
        for stage, ms in body["timings_ms"].items():
            stages.setdefault(stage, []).append(ms / 1000)
    return {
        "wall_s": summarize(walls),
        "stages_s": {k: summarize(v) for k, v in stages.items()},
        "runs_with_a_degradation_note": degraded,
    }


def clear_mask_cache() -> int:
    """Empty `vms-masks` so the first request for a keyframe really computes the mask (the
    cache is derived data: it is rebuilt on demand)."""
    import boto3
    from vms_common.config import StorageSettings

    st = StorageSettings()
    client = boto3.client(
        "s3",
        endpoint_url=st.endpoint_url,
        aws_access_key_id=st.access_key,
        aws_secret_access_key=st.secret_key,
    )
    removed = 0
    for page in client.get_paginator("list_objects_v2").paginate(Bucket="vms-masks"):
        for obj in page.get("Contents", []):
            client.delete_object(Bucket="vms-masks", Key=obj["Key"])
            removed += 1
    return removed


async def measure_grounding(client: httpx.AsyncClient) -> dict:
    clear_mask_cache()
    body = await search(client, "a person carrying a backpack", "fast")
    cold: list[float] = []
    warm: list[float] = []
    for r in body["results"][:5]:
        payload = {"search_id": body["search_id"], "result_id": r["result_id"]}
        for bucket in (cold, warm):
            t = time.perf_counter()
            resp = await client.post("/search/grounding", json=payload, timeout=120)
            if resp.status_code == 200:
                bucket.append(time.perf_counter() - t)
    return {"first_request_s": summarize(cold), "repeat_request_s": summarize(warm)}


async def measure_assistant(client: httpx.AsyncClient, user_id: str, questions: list[str]) -> dict:
    sid = (await client.post("/assistant/sessions", headers={"X-User-Id": user_id})).json()["id"]
    first_tool, first_token, total = [], [], []
    for q in questions:
        t0 = time.perf_counter()
        seen_tool = seen_token = False
        async with client.stream(
            "POST",
            f"/assistant/sessions/{sid}/messages",
            json={"content": q},
            headers={"X-User-Id": user_id},
            timeout=300,
        ) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("event: tool_result") and not seen_tool:
                    first_tool.append(time.perf_counter() - t0)
                    seen_tool = True
                elif line.startswith("event: token") and not seen_token:
                    first_token.append(time.perf_counter() - t0)
                    seen_token = True
                elif line.startswith("event: done"):
                    break
        total.append(time.perf_counter() - t0)
    return {
        "to_lookup_result_and_first_sentence_s": summarize(first_tool),
        "to_first_word_s": summarize(first_token),
        "whole_turn_s": summarize(total),
    }


async def measure_database(engine) -> dict:
    out: dict = {}
    async with engine.connect() as c:
        rows = (
            await c.execute(
                text(
                    "SELECT extract(epoch from indexed_at - end_ts) FROM media.segments "
                    "WHERE end_ts > now() - interval '24 hours' AND indexed_at > end_ts"
                )
            )
        ).all()
        out["segment_to_searchable_s"] = summarize([float(r[0]) for r in rows])
        rows = (
            await c.execute(
                text(
                    "SELECT extract(epoch from finished_at - started_at) FROM reasoning.jobs "
                    "WHERE status = 'done' AND finished_at IS NOT NULL AND started_at IS NOT NULL"
                )
            )
        ).all()
        out["reasoning_job_s"] = summarize([float(r[0]) for r in rows])
        rows = (
            await c.execute(
                text(
                    "SELECT extract(epoch from finished_at - created_at) FROM reasoning.daily_reports "  # noqa: E501
                    "WHERE status = 'ready' AND finished_at IS NOT NULL"
                )
            )
        ).all()
        out["daily_report_s"] = summarize([float(r[0]) for r in rows])
        row = (
            await c.execute(
                text(
                    "SELECT count(*), count(*) FILTER (WHERE status = 'verified'), "
                    "count(*) FILTER (WHERE status = 'rejected'), "
                    "count(*) FILTER (WHERE status = 'skipped'), "
                    "percentile_cont(0.5) WITHIN GROUP (ORDER BY (verification->>'latency_ms')::float), "  # noqa: E501
                    "percentile_cont(0.95) WITHIN GROUP (ORDER BY (verification->>'latency_ms')::float) "  # noqa: E501
                    "FROM events.events WHERE verification ? 'latency_ms'"
                )
            )
        ).one()
        out["vlm_gate"] = {
            "decided": row[0],
            "verified": row[1],
            "rejected": row[2],
            "skipped": row[3],
            "latency_p50_s": round((row[4] or 0) / 1000, 2),
            "latency_p95_s": round((row[5] or 0) / 1000, 2),
        }
    return out


def table(title: str, rows: dict[str, dict]) -> str:
    lines = [f"### {title}", "", "| | n | p50 | p95 | min | max |", "|---|---|---|---|---|---|"]
    for name, s in rows.items():
        lines.append(f"| {name} | {s['n']} | {s['p50']} | {s['p95']} | {s['min']} | {s['max']} |")
    return "\n".join(lines) + "\n"


def markdown(r: dict) -> str:
    out = [
        "# P7-D4 — Latency of the running stack",
        "",
        f"**Measured {r['measured_at']}** on the build machine (RTX 3050 Laptop 4 GB, Ryzen 5 5600H, "  # noqa: E501
        "14 GB RAM), local profile: text tasks on `qwen2.5:3b`, vision tasks on `qwen2.5vl:3b` "
        "through Ollama, SigLIP 2 and SAM 2.1-tiny on CPU. One real camera (`cam01`).",
        "",
        "Produced by `ml/evaluation/latency/measure.py`. Times are seconds as an operator sees "
        "them (HTTP through the real services); percentiles come from the `n` shown, so treat "
        "p95 of a small `n` as a rough upper bound, not a distribution.",
        "",
    ]
    out.append(table("Text search, fast mode (end to end)", {"wall": r["search_fast"]["wall_s"]}))
    out.append(table("Fast mode, by stage", r["search_fast"]["stages_s"]))
    out.append(
        table("Text search, reason mode (end to end)", {"wall": r["search_reason"]["wall_s"]})
    )
    out.append(table("Reason mode, by stage", r["search_reason"]["stages_s"]))
    out.append(table("Object masks (SAM 2.1-tiny, CPU)", r["grounding"]))
    out.append(table("Assistant", r["assistant"]))
    db = r["database"]
    out.append(
        table(
            "Pipeline and background work",
            {
                "segment end → searchable": db["segment_to_searchable_s"],
                "reasoning job (all stages)": db["reasoning_job_s"],
                "daily report": db["daily_report_s"],
            },
        )
    )
    g = db["vlm_gate"]
    out.append(
        f"VLM gate: {g['decided']} candidates decided ({g['verified']} verified, {g['rejected']} "
        f"rejected, {g['skipped']} skipped); model time per candidate p50 {g['latency_p50_s']} s, "
        f"p95 {g['latency_p95_s']} s.\n"
    )
    out.append(
        "How to read these. Search, mask and assistant timings were taken with the GPU otherwise "
        "idle (perception and the VLM gate stopped; the model already loaded). The pipeline "
        "lag, reasoning-job and gate figures come from the stack's earlier hours, when perception, "
        "the gate, the reasoning worker and Ollama all competed for the 4 GB card — they describe "
        "that contended run, and the gate's p95 includes minutes spent with the model running on "
        "the CPU. The assistant's first sentence is the lookup's own header line, so "
        '"first sentence" arrives with the tool result; the model\'s own words follow.\n'
    )
    out.append(
        f"Searches that carried a degradation note: fast {r['search_fast']['runs_with_a_degradation_note']}, "  # noqa: E501
        f"reason {r['search_reason']['runs_with_a_degradation_note']}.\n"
    )
    return "\n".join(out)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrieval-url", default="http://localhost:8010")
    ap.add_argument("--fast", type=int, default=30)
    ap.add_argument("--reason", type=int, default=4)
    ap.add_argument("--assistant", type=int, default=4)
    ap.add_argument("--out", default="ml/evaluation/results")
    args = ap.parse_args()

    engine = create_engine(DatabaseSettings())
    async with engine.connect() as c:
        user_id = (
            await c.execute(text("SELECT id::text FROM core.users ORDER BY created_at LIMIT 1"))
        ).scalar_one()
    result: dict = {"measured_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")}
    async with httpx.AsyncClient(base_url=args.retrieval_url, timeout=300) as client:
        print("fast search…", flush=True)  # noqa: T201
        seed = time.time_ns()
        result["search_fast"] = await measure_search(
            client, fresh_queries(args.fast, seed), "fast", args.fast
        )
        print("grounding…", flush=True)  # noqa: T201
        result["grounding"] = await measure_grounding(client)
        print("reason search…", flush=True)  # noqa: T201
        result["search_reason"] = await measure_search(
            client, fresh_queries(args.reason + 20, seed + 1)[-args.reason :], "reason", args.reason
        )
        print("assistant…", flush=True)  # noqa: T201
        result["assistant"] = await measure_assistant(
            client, user_id, ASSISTANT_QUESTIONS[: args.assistant]
        )
    result["database"] = await measure_database(engine)
    await engine.dispose()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - once, at the end
    (out / "p7-latency.json").write_text(json.dumps(result, indent=1))  # noqa: ASYNC240
    (out / "p7-latency.md").write_text(markdown(result))  # noqa: ASYNC240
    print(markdown(result))  # noqa: T201


if __name__ == "__main__":
    asyncio.run(main())
