#!/usr/bin/env python
"""Endurance smoke test (backlog.md P1-D5 AC): consume `vms.segments.v1` for
`--duration-minutes` and report any gap in each camera's sequence numbers.

Needs the full stack running (infra + tools (camera_sim) + core (ingestion),
or real cameras) — this is an operational script, not a pytest unit test,
because it needs wall-clock time and live infra. Not run in the environment
this story was built in (no Docker daemon there) — see
services/ingestion/README.md.

Usage:
    uv run --package vms-ingestion python tests/smoke/check_no_missing_segments.py \
        --bootstrap-servers localhost:9092 --duration-minutes 30
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta

from aiokafka import AIOKafkaConsumer

SEGMENTS_TOPIC = "vms.segments.v1"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-servers", default="localhost:9092")
    parser.add_argument("--duration-minutes", type=float, default=30.0)
    parser.add_argument(
        "--group-id",
        default="ingestion-smoke-check",
        help="fresh consumer group so this reads from 'now', not history",
    )
    return parser.parse_args(argv)


async def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    deadline = datetime.now(UTC) + timedelta(minutes=args.duration_minutes)

    consumer = AIOKafkaConsumer(
        SEGMENTS_TOPIC,
        bootstrap_servers=args.bootstrap_servers,
        group_id=args.group_id,
        auto_offset_reset="latest",
        enable_auto_commit=False,
    )
    await consumer.start()

    seen: dict[str, set[int]] = {}
    total = 0
    try:
        while datetime.now(UTC) < deadline:
            timeout_ms = max(1000, int((deadline - datetime.now(UTC)).total_seconds() * 1000))
            try:
                record = await asyncio.wait_for(
                    consumer.getone(), timeout=min(timeout_ms, 5000) / 1000
                )
            except TimeoutError:
                continue
            message = json.loads(record.value)
            camera_id = message["camera_id"]
            seq = int(message["segment_id"].rsplit("_", 1)[-1])
            seen.setdefault(camera_id, set()).add(seq)
            total += 1
    finally:
        await consumer.stop()

    print(
        f"observed {total} segments across {len(seen)} camera(s) over "
        f"{args.duration_minutes:.1f} min"
    )

    ok = True
    for camera_id, seqs in sorted(seen.items()):
        expected = set(range(min(seqs), max(seqs) + 1))
        missing = sorted(expected - seqs)
        status = "OK" if not missing else "MISSING SEGMENTS"
        print(f"  {camera_id}: {len(seqs)} segments, seq {min(seqs)}..{max(seqs)} [{status}]")
        if missing:
            ok = False
            print(f"    missing seq numbers: {missing}")

    if not seen:
        print("no segments observed at all — is the stack actually running?")
        ok = False

    return 0 if ok else 1


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
