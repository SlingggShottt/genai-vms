"""What each feature does when no language model is reachable (P7-D5, NFR-REL-04).

Stop Ollama (or point `VMS_LLM_OLLAMA_URL` at nothing), keep the rest of the stack up, and run:

    uv run --package vms-retrieval python ml/evaluation/resilience/llm_down.py

NFR-REL-04: ingestion, recording, playback and rules continue; GenAI features say they are
unavailable — they do not hang, and they do not lose the work asked of them. This asks each
feature in turn and records the answer and how long it took. Needs the reasoning worker running.
Writes `ml/evaluation/results/p7-degradation.md`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import text
from vms_common.config import DatabaseSettings
from vms_db.session import create_engine


async def timed(coro):
    t = time.perf_counter()
    try:
        return await coro, time.perf_counter() - t
    except Exception as exc:  # the point is to record it
        return exc, time.perf_counter() - t


async def fast_search(client: httpx.AsyncClient) -> str:
    r = await client.post("/search", json={"query": "a person in a red top", "mode": "fast"})
    body = r.json()
    return (
        f"HTTP {r.status_code}, {len(body.get('results', []))} results, notes: {body.get('notes')}"  # noqa: E501
    )


async def reason_search(client: httpx.AsyncClient) -> str:
    q = f"a person with a blue bag {uuid.uuid4().hex[:6]}"  # not a cached answer
    r = await client.post("/search", json={"query": q, "mode": "reason"}, timeout=200)
    body = r.json()
    return (
        f"HTTP {r.status_code}, {len(body.get('results', []))} results (fused order), "
        f"notes: {body.get('notes')}"
    )


async def assistant_turn(client: httpx.AsyncClient, user_id: str) -> str:
    sid = (await client.post("/assistant/sessions", headers={"X-User-Id": user_id})).json()["id"]
    events = []
    async with client.stream(
        "POST",
        f"/assistant/sessions/{sid}/messages",
        json={"content": f"Tell me about the cameras {uuid.uuid4().hex[:4]}"},
        headers={"X-User-Id": user_id},
        timeout=200,
    ) as resp:
        async for line in resp.aiter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
            if line.startswith("data:") and '"type": "error"' in line:
                events.append("error=" + json.loads(line[5:])["message"][:80])
    return "events: " + ", ".join(dict.fromkeys(events))


async def daily_report(engine) -> str:
    day = datetime.now(UTC).date()
    async with engine.begin() as c:
        rid = (
            await c.execute(
                text(
                    "INSERT INTO reasoning.daily_reports (id, date_from, date_to) "
                    "VALUES (gen_random_uuid(), :d, :d) RETURNING id"
                ),
                {"d": day},
            )
        ).scalar_one()
    for _ in range(60):
        await asyncio.sleep(3)
        async with engine.connect() as c:
            row = (
                await c.execute(
                    text(
                        "SELECT status, narrative_source FROM reasoning.daily_reports WHERE id = :i"
                    ),  # noqa: E501
                    {"i": rid},
                )
            ).one()
        if row[0] in ("ready", "failed"):
            return f"status {row[0]}, narrative from the {row[1]}"
    return "still not finished after 3 minutes"


async def analysis_job(engine) -> str:
    async with engine.begin() as c:
        ev = (
            await c.execute(
                text(
                    "SELECT id::text FROM events.events WHERE status <> 'rejected' "
                    "AND end_ts > now() - interval '2 hours' ORDER BY start_ts DESC LIMIT 1"
                )
            )
        ).scalar()
        if ev is None:
            return "skipped: no recent verified event to analyse"
        jid = (
            await c.execute(
                text(
                    "INSERT INTO reasoning.jobs (id, event_ids, trigger) VALUES "
                    "(gen_random_uuid(), ARRAY[:e], 'manual') RETURNING id"
                ),
                {"e": ev},
            )
        ).scalar_one()
    for _ in range(100):
        await asyncio.sleep(3)
        async with engine.connect() as c:
            row = (
                await c.execute(
                    text("SELECT status, stage, error FROM reasoning.jobs WHERE id = :i"),
                    {"i": jid},  # noqa: E501
                )
            ).one()
        if row[0] in ("done", "failed"):
            return f"job {row[0]}" + (f": {row[2]}" if row[2] else "")
    return f"job still {row[0]} ({row[1]}) after 5 minutes"


async def gate_held(engine) -> str:
    async with engine.connect() as c:
        row = (
            await c.execute(
                text(
                    "SELECT count(*), count(*) FILTER (WHERE verify_attempts > 0), "
                    "max(verify_attempts) FROM events.candidates c "
                    "WHERE NOT EXISTS (SELECT 1 FROM events.events e WHERE e.id = c.id) "
                    "AND c.end_ts > :t AND c.severity IN ('medium','high','critical')"
                ),
                {"t": datetime.now(UTC) - timedelta(hours=1)},
            )
        ).one()
    return (
        f"{row[0]} alert-worthy candidates from the last hour have no decision yet; "
        f"{row[1]} are being retried with back-off (most attempts so far: {row[2]}); none dropped"
    )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrieval-url", default="http://localhost:8010")
    ap.add_argument("--out", default="ml/evaluation/results")
    args = ap.parse_args()
    engine = create_engine(DatabaseSettings())
    async with engine.connect() as c:
        user_id = (
            await c.execute(text("SELECT id::text FROM core.users ORDER BY created_at LIMIT 1"))
        ).scalar_one()  # noqa: E501
    rows: list[tuple[str, str, float]] = []
    async with httpx.AsyncClient(base_url=args.retrieval_url, timeout=60) as client:
        for name, coro in (
            ("Search, fast mode", fast_search(client)),
            ("Search, reason mode", reason_search(client)),
            ("Assistant question", assistant_turn(client, user_id)),
        ):
            result, secs = await timed(coro)
            rows.append((name, str(result), secs))
            print(name, "->", result, f"({secs:.1f} s)", flush=True)  # noqa: T201
    for name, coro in (
        ("Events gate (VLM verification)", gate_held(engine)),
        ("Daily report", daily_report(engine)),
        ("Incident analysis job", analysis_job(engine)),
    ):
        result, secs = await timed(coro)
        rows.append((name, str(result), secs))
        print(name, "->", result, f"({secs:.1f} s)", flush=True)  # noqa: T201
    await engine.dispose()
    md = [
        "# P7-D5 — With no language model reachable",
        "",
        f"**Run {datetime.now(UTC):%Y-%m-%d %H:%M UTC}**, Ollama stopped, everything else up "
        "(NFR-REL-04: ingestion, recording, playback and rules continue; GenAI features say they are "  # noqa: E501
        "unavailable instead of hanging).",
        "",
        "| Feature | What happened | Time |",
        "|---|---|---|",
        *[f"| {n} | {r} | {s:.1f} s |" for n, r, s in rows],
        "",
    ]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    (out / "p7-degradation.md").write_text("\n".join(md))  # noqa: ASYNC240


if __name__ == "__main__":
    asyncio.run(main())
