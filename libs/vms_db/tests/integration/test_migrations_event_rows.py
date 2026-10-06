"""Integration test: migration 0008 creates `events.events` and adds the gate's queue columns to
`events.candidates`; the table refuses an impossible row (P3-D4). Run via `make test-int`
(needs Docker)."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer
from vms_db.models import Event

pytestmark = pytest.mark.integration

VMS_DB_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


def _async_dsn(container: PostgresContainer) -> str:
    return container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


def _config() -> Config:
    return Config(str(VMS_DB_ROOT / "alembic.ini"))


def test_migration_0008_creates_events_and_the_queue_columns_and_the_table_refuses_bad_rows() -> (
    None
):
    with PostgresContainer("postgres:16-alpine") as pg:
        dsn = _async_dsn(pg)
        os.environ["VMS_DB_DSN"] = dsn
        try:
            command.upgrade(_config(), "head")
            tables, columns = asyncio.run(_shape(dsn))
            assert "events" in tables
            assert {"verify_attempts", "verify_first_at", "verify_not_before"} <= columns
            asyncio.run(_exercise(dsn))
        finally:
            os.environ.pop("VMS_DB_DSN", None)


def test_migration_0008_downgrades_cleanly_and_can_be_reapplied() -> None:
    with PostgresContainer("postgres:16-alpine") as pg:
        dsn = _async_dsn(pg)
        os.environ["VMS_DB_DSN"] = dsn
        try:
            command.upgrade(_config(), "head")
            command.downgrade(_config(), "0007")
            tables, columns = asyncio.run(_shape(dsn))
            assert "events" not in tables and "candidates" in tables
            assert not {"verify_attempts", "verify_first_at", "verify_not_before"} & columns
            command.upgrade(_config(), "head")
            tables, columns = asyncio.run(_shape(dsn))
            assert "events" in tables and "verify_attempts" in columns
        finally:
            os.environ.pop("VMS_DB_DSN", None)


async def _shape(dsn: str) -> tuple[set[str], set[str]]:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:

            def read(c):  # noqa: ANN001, ANN202
                insp = inspect(c)
                return (
                    set(insp.get_table_names(schema="events")),
                    {col["name"] for col in insp.get_columns("candidates", schema="events")},
                )

            return await conn.run_sync(read)
    finally:
        await engine.dispose()


def _event(**kw: object) -> Event:
    args: dict[str, object] = {
        "id": uuid.uuid4(),
        "site_id": "site",
        "camera_id": "cam02",
        "event_type": "intrusion",
        "severity": "high",
        "rule_id": "intrusion.restricted",
        "rule_score": 0.9,
        "start_ts": NOW,
        "end_ts": NOW + timedelta(seconds=20),
        "status": "verified",
        "verification": {"status": "verified", "confidence": 0.9},
    }
    return Event(**(args | kw))


async def _exercise(dsn: str) -> None:
    engine = create_async_engine(dsn)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def rejected(row: object) -> bool:
        """True if the database refuses this row (each attempt gets its own transaction)."""
        async with factory() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                return True
            return False

    try:
        later = NOW + timedelta(minutes=1)
        # the rows that are allowed
        assert not await rejected(_event()), "a verified event waiting to be published"
        assert not await rejected(_event(status="verified", published_at=later))
        assert not await rejected(_event(status="skipped"))
        assert not await rejected(_event(status="rejected")), (
            "a rejected event, kept with its reason"
        )
        assert not await rejected(_event(start_ts=NOW, end_ts=NOW)), "an instant"

        # one decision per candidate
        same = uuid.uuid4()
        assert not await rejected(_event(id=same))
        assert await rejected(_event(id=same)), "a second decision for the same candidate"

        # and the rows that are not
        assert await rejected(_event(status="maybe")), "unknown status"
        assert await rejected(_event(severity="meh")), "unknown severity"
        assert await rejected(_event(end_ts=NOW - timedelta(seconds=1))), "ends before it starts"
        assert await rejected(_event(rule_score=1.5)), "score above 1"
        assert await rejected(_event(rule_score=-0.1)), "score below 0"
        assert await rejected(_event(status="rejected", published_at=later)), (
            "a rejected event that was published"
        )
        assert await rejected(_event(verification=None)), "no verification record (JSON null)"
        assert await rejected(_event(verification=[])), (
            "a verification record that is not an object"
        )

        # a verified/skipped row with no publish time is the outbox's work list, nothing else is
        async with factory() as session:
            waiting = (
                (
                    await session.execute(
                        text(
                            "SELECT status FROM events.events "
                            "WHERE status IN ('verified', 'skipped') AND published_at IS NULL "
                            "ORDER BY status"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert set(waiting) == {"verified", "skipped"}
    finally:
        await engine.dispose()
