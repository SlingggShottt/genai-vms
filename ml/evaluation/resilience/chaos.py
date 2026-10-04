"""Restart workers mid-stream and check nothing was lost or doubled (P7-D5, NFR-REL-01…03).

Run it while the camera simulator and perception are producing segments:

    docker start vms-camera-sim     # and perception on the host
    sg docker -c "uv run --package vms-retrieval python ml/evaluation/resilience/chaos.py \\
        --duration 420 --interval 70 --targets indexer,events,correlation"

Every `--interval` seconds it `docker restart`s the next target, for `--duration` seconds, then
waits for the pipeline to go quiet and checks, for the segments recorded during the run:

  I1  no gap in the segment sequence of any camera (the recorder was never restarted);
  I2  every segment row has its twin in object storage;
  I3  Qdrant holds exactly the frame and track points those twins describe — none missing (a lost
      message), none extra (a duplicate cannot exist: point ids are deterministic);
  I4  no verified event sits in two live correlation groups.

The services it restarts are consumers (at-least-once + idempotent writes); the recorder
(`ingestion`) is deliberately not a target: while it is down nothing is recording, which is a gap in
the footage, not a lost message.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import boto3
from aiokafka.structs import TopicPartition
from botocore.exceptions import ClientError
from qdrant_client import AsyncQdrantClient, models
from sqlalchemy import text
from vms_common.config import DatabaseSettings, QdrantSettings, StorageSettings
from vms_common.contracts.twin import TwinV1
from vms_common.storage.uri import parse_uri
from vms_db.session import create_engine

MIN_SEGMENTS = 10  # fewer than this and the run proved nothing
SEQ = re.compile(r"^(?P<cam>.+?)_(?P<ts>\d{8}T\d{6}Z)_(?P<seq>\d+)$")


def restart(container: str) -> float:
    t = time.perf_counter()
    subprocess.run(["docker", "restart", container], check=True, capture_output=True)  # noqa: S603, S607
    return time.perf_counter() - t


PIPELINE_GROUPS = (
    ("perception", "vms.segments.v1"),
    ("indexer", "vms.twin.v1"),
    ("events", "vms.twin.v1"),
    ("correlation", "vms.events.v1"),
)


async def lag(group: str, topic: str) -> int:
    """Messages on `topic` that consumer group `group` has not yet committed past."""
    from aiokafka import AIOKafkaConsumer
    from vms_common.config import KafkaSettings

    consumer = AIOKafkaConsumer(
        bootstrap_servers=KafkaSettings().bootstrap_servers,
        group_id=group,
        enable_auto_commit=False,
    )
    await consumer.start()
    try:
        await consumer.topics()  # loads the metadata `partitions_for_topic` reads
        partitions = [TopicPartition(topic, p) for p in consumer.partitions_for_topic(topic) or ()]
        ends = await consumer.end_offsets(partitions)
        total = 0
        for tp in partitions:
            total += ends[tp] - (await consumer.committed(tp) or 0)
        return total
    finally:
        await consumer.stop()


async def wait_drained(timeout_s: int = 900) -> dict[str, int]:
    """Until every pipeline consumer group has committed everything on its topic. Returns the lag
    left when it gave up (all zero on success)."""
    deadline = time.monotonic() + timeout_s
    left: dict[str, int] = {}
    while time.monotonic() < deadline:
        left = {g: await lag(g, t) for g, t in PIPELINE_GROUPS}
        if not any(left.values()):
            return left
        await asyncio.sleep(10)
    return left


def gaps(segment_ids: list[str]) -> dict[str, list[int]]:
    """Missing sequence numbers per camera (ids are `<camera>_<time>_<seq>`; the sequence is
    continuous for one recorder run)."""
    by_cam: dict[str, list[int]] = {}
    for sid in segment_ids:
        m = SEQ.match(sid)
        if m:
            by_cam.setdefault(m["cam"], []).append(int(m["seq"]))
    out: dict[str, list[int]] = {}
    for cam, seqs in by_cam.items():
        seqs.sort()
        missing = sorted(set(range(seqs[0], seqs[-1] + 1)) - set(seqs))
        if missing:
            out[cam] = missing
    return out


async def check(engine, qdrant: AsyncQdrantClient, since: datetime) -> dict:
    st = StorageSettings()
    s3 = boto3.client(
        "s3",
        endpoint_url=st.endpoint_url,
        aws_access_key_id=st.access_key,
        aws_secret_access_key=st.secret_key,
    )
    async with engine.connect() as c:
        rows = (
            await c.execute(
                text(
                    "SELECT segment_id, twin_uri FROM media.segments WHERE indexed_at >= :t "
                    "ORDER BY start_ts"
                ),
                {"t": since},
            )
        ).all()
        dup_events = (
            await c.execute(
                text(
                    "SELECT count(*) FROM (SELECT e FROM events.correlation_groups g, "
                    "unnest(g.event_ids) e WHERE g.status <> 'merged' GROUP BY e "
                    "HAVING count(*) > 1) d"
                )
            )
        ).scalar_one()
    result: dict = {"segments": len(rows)}

    result["I1_sequence_gaps"] = gaps([r[0] for r in rows])

    missing_twins, expected_frames, expected_tracks = [], 0, 0
    for sid, uri in rows:
        loc = parse_uri(uri)
        try:
            body = s3.get_object(Bucket=loc.bucket, Key=loc.key)["Body"].read()
        except ClientError:
            missing_twins.append(sid)
            continue
        twin = TwinV1.model_validate(json.loads(body))
        expected_frames += len(twin.frames)
        expected_tracks += len(twin.tracks)
    result["I2_segments_without_twin"] = missing_twins

    ids = [r[0] for r in rows]
    flt = models.Filter(
        must=[models.FieldCondition(key="segment_id", match=models.MatchAny(any=ids))]
    )
    frames = (await qdrant.count("frames", count_filter=flt, exact=True)).count
    # tracks carry a list of segment ids; a track seen in two segments is one point per segment
    tracks = (
        await qdrant.count(
            "tracks",
            count_filter=models.Filter(
                must=[models.FieldCondition(key="segment_ids", match=models.MatchAny(any=ids))]
            ),
            exact=True,
        )
    ).count
    result["I3_frames"] = {"expected": expected_frames, "in_qdrant": frames}
    result["I3_tracks"] = {"expected": expected_tracks, "in_qdrant": tracks}
    result["I4_events_in_two_groups"] = dup_events
    result["passed"] = (
        len(rows) >= MIN_SEGMENTS
        and not result["I1_sequence_gaps"]
        and not missing_twins
        and frames == expected_frames
        and tracks == expected_tracks
        and dup_events == 0
    )
    return result


def markdown(r: dict) -> str:
    def ok(b: bool) -> str:
        return "pass" if b else "**FAIL**"

    f, t = r["I3_frames"], r["I3_tracks"]
    return "\n".join(
        [
            "# P7-D5 — Restarting workers mid-stream",
            "",
            f"**Run {r['started']}**, {r['duration_s']} s, one `docker restart` every "
            f"{r['interval_s']} s of: {', '.join(r['targets'])}. {r['segments']} segments were "
            "analysed and indexed during the run"
            + (
                " — too few to prove anything, so this run is inconclusive."
                if r["segments"] < MIN_SEGMENTS
                else "."
            ),
            "",
            "Consumer lag left when the checks ran: "
            + ", ".join(f"{g} {n}" for g, n in r["lag_left"].items())
            + ".",
            "",
            "| Invariant | Result |",
            "|---|---|",
            f"| I1 no gap in any camera's segment sequence | {ok(not r['I1_sequence_gaps'])} "
            f"{r['I1_sequence_gaps'] or ''} |",
            f"| I2 every segment row has its twin in storage | {ok(not r['I2_segments_without_twin'])} "  # noqa: E501
            f"({len(r['I2_segments_without_twin'])} missing) |",
            f"| I3 frame points in Qdrant = frames in the twins | {ok(f['expected'] == f['in_qdrant'])} "  # noqa: E501
            f"({f['in_qdrant']} / {f['expected']}) |",
            f"| I3 track points in Qdrant = tracks in the twins | {ok(t['expected'] == t['in_qdrant'])} "  # noqa: E501
            f"({t['in_qdrant']} / {t['expected']}) |",
            f"| I4 no event in two live correlation groups | {ok(r['I4_events_in_two_groups'] == 0)} "  # noqa: E501
            f"({r['I4_events_in_two_groups']}) |",
            "",
            "Restarts: " + ", ".join(f"{n} ({s:.1f} s)" for n, s in r["restarts"]),
            "",
            f"**{'All invariants held.' if r['passed'] else 'Not a pass — see above.'}**",
            "",
        ]
    )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=420)
    ap.add_argument("--interval", type=int, default=70)
    ap.add_argument("--targets", default="indexer,events,correlation")
    ap.add_argument(
        "--stop-source",
        default="vms-camera-sim",
        help="container to stop when the restarts end, so the pipeline can drain (empty = leave it)",  # noqa: E501
    )
    ap.add_argument("--out", default="ml/evaluation/results")
    args = ap.parse_args()
    targets = [f"vms-{t.strip()}" for t in args.targets.split(",") if t.strip()]

    engine = create_engine(DatabaseSettings())
    qdrant = AsyncQdrantClient(url=QdrantSettings().url)
    started = datetime.now(UTC)
    restarts: list[tuple[str, float]] = []
    t_end = time.monotonic() + args.duration
    i = 0
    while time.monotonic() < t_end:
        await asyncio.sleep(min(args.interval, max(0, t_end - time.monotonic())))
        if time.monotonic() >= t_end:
            break
        name = targets[i % len(targets)]
        restarts.append((name, await asyncio.to_thread(restart, name)))
        print(f"restarted {name}", flush=True)  # noqa: T201
        i += 1
    if args.stop_source:
        await asyncio.to_thread(
            subprocess.run,
            ["docker", "stop", args.stop_source],  # noqa: S607
            check=False,
            capture_output=True,
        )
    print("waiting for the consumers to catch up…", flush=True)  # noqa: T201
    lag_left = await wait_drained()
    result = await check(engine, qdrant, started)
    result.update(
        lag_left=lag_left,
        started=started.strftime("%Y-%m-%d %H:%M UTC"),
        duration_s=args.duration,
        interval_s=args.interval,
        targets=[t.removeprefix("vms-") for t in targets],
        restarts=restarts,
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    (out / "p7-resilience.json").write_text(json.dumps(result, indent=1, default=str))  # noqa: ASYNC240
    (out / "p7-resilience.md").write_text(markdown(result))  # noqa: ASYNC240
    print(markdown(result))  # noqa: T201
    await engine.dispose()
    await qdrant.close()


if __name__ == "__main__":
    asyncio.run(main())
