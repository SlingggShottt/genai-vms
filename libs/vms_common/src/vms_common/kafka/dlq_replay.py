"""Replay dead-lettered messages back to the topic they came from (NFR-REL-02, P7-D5).

A message lands in `vms.dlq.v1` after three failed handlings, with headers `x-origin-topic`,
`x-error` and `x-attempts` (see `BaseConsumer`). Once the cause is fixed — a service deployed, a
database back — this puts them back:

    python -m vms_common.kafka.dlq_replay --list                       # what is in there
    python -m vms_common.kafka.dlq_replay --topic vms.twin.v1 --dry-run
    python -m vms_common.kafka.dlq_replay --topic vms.twin.v1 --limit 50

It reads with its own consumer group and commits only after a message has been re-published, so a
second run replays only what is new (or what a crash interrupted). Consumers are idempotent
(design §15), so a message that was in fact handled meanwhile is harmless.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Iterable
from dataclasses import dataclass

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from vms_common.config import KafkaSettings

GROUP = "vms-dlq-replay"


@dataclass(frozen=True)
class DeadLetter:
    origin_topic: str | None
    error: str
    attempts: int
    key: bytes | None
    value: bytes
    partition: int
    offset: int


def _header(headers: Iterable[tuple[str, bytes]] | None, name: str) -> str | None:
    for k, v in headers or ():
        if k == name:
            return v.decode(errors="replace")
    return None


def parse(record) -> DeadLetter:
    attempts = _header(record.headers, "x-attempts")
    return DeadLetter(
        origin_topic=_header(record.headers, "x-origin-topic"),
        error=_header(record.headers, "x-error") or "",
        attempts=int(attempts) if attempts and attempts.isdigit() else 0,
        key=record.key,
        value=record.value,
        partition=record.partition,
        offset=record.offset,
    )


def plan(
    letters: Iterable[DeadLetter], *, topic: str | None, limit: int | None
) -> list[DeadLetter]:
    """What would be replayed: letters for `topic` (all if None) that know where they came from,
    oldest first, at most `limit`."""
    chosen = [d for d in letters if d.origin_topic and (topic is None or d.origin_topic == topic)]
    return chosen[:limit] if limit is not None else chosen


async def _read_new(bootstrap: str, dlq_topic: str) -> tuple[AIOKafkaConsumer, list]:
    consumer = AIOKafkaConsumer(
        dlq_topic,
        bootstrap_servers=bootstrap,
        group_id=GROUP,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    records: list = []
    while True:
        batch = await consumer.getmany(timeout_ms=3000, max_records=500)
        got = [r for rs in batch.values() for r in rs]
        if not got:
            break
        records.extend(got)
    return consumer, records


async def run(args: argparse.Namespace) -> int:
    settings = KafkaSettings()
    consumer, records = await _read_new(settings.bootstrap_servers, settings.dlq_topic)
    try:
        letters = [parse(r) for r in records]
        if args.list:
            for d in letters:
                print(  # noqa: T201
                    f"{d.partition}:{d.offset}  {d.origin_topic or '?':<22} "
                    f"attempts={d.attempts}  {d.error[:90]}"
                )
            print(f"{len(letters)} dead letter(s) not yet replayed")  # noqa: T201
            return 0
        todo = plan(letters, topic=args.topic, limit=args.limit)
        if args.dry_run or not todo:
            print(f"{'would replay' if args.dry_run else 'nothing to replay:'} {len(todo)}")  # noqa: T201
            return 0
        producer = AIOKafkaProducer(bootstrap_servers=settings.bootstrap_servers)
        await producer.start()
        try:
            for d in todo:
                await producer.send_and_wait(d.origin_topic, value=d.value, key=d.key)
        finally:
            await producer.stop()
        # Commit past the last record we handled; letters we skipped (other topics) before it
        # are not replayed later, so only advance when every letter up to there was chosen.
        if len(todo) == len(letters):
            await consumer.commit()
        print(f"replayed {len(todo)} message(s)")  # noqa: T201
        return 0
    finally:
        await consumer.stop()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--topic", help="only letters that came from this topic")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--list", action="store_true", help="show the dead letters and exit")
    ap.add_argument("--dry-run", action="store_true")
    raise SystemExit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
