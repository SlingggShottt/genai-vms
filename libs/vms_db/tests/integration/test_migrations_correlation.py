"""Integration test: migration 0006 creates the correlation tables and they refuse malformed
rows (P3-J2: "Persists events.correlation_groups / correlation_links"). Run via `make test-int`."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer
from vms_db.models import CorrelationGroup, CorrelationLinkRow

pytestmark = pytest.mark.integration

VMS_DB_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


def _async_dsn(container: PostgresContainer) -> str:
    return container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


def _config() -> Config:
    return Config(str(VMS_DB_ROOT / "alembic.ini"))


def test_migration_0006_creates_the_tables_and_they_enforce_their_rules() -> None:
    with PostgresContainer("postgres:16-alpine") as pg:
        dsn = _async_dsn(pg)
        os.environ["VMS_DB_DSN"] = dsn
        try:
            command.upgrade(_config(), "head")
            tables = asyncio.run(_tables(dsn))
            asyncio.run(_exercise(dsn))
        finally:
            os.environ.pop("VMS_DB_DSN", None)
    assert {"correlation_groups", "correlation_links", "candidates"} <= tables


def test_migration_0006_downgrades_cleanly_and_can_be_reapplied() -> None:
    with PostgresContainer("postgres:16-alpine") as pg:
        dsn = _async_dsn(pg)
        os.environ["VMS_DB_DSN"] = dsn
        try:
            command.upgrade(_config(), "head")
            command.downgrade(_config(), "0005")
            tables = asyncio.run(_tables(dsn))
            assert "correlation_groups" not in tables and "correlation_links" not in tables
            assert "candidates" in tables  # 0004's table is untouched
            command.upgrade(_config(), "head")
            assert "correlation_groups" in asyncio.run(_tables(dsn))
        finally:
            os.environ.pop("VMS_DB_DSN", None)


async def _tables(dsn: str) -> set[str]:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(lambda c: set(inspect(c).get_table_names(schema="events")))
    finally:
        await engine.dispose()


def _group(**kw: object) -> CorrelationGroup:
    event = str(uuid.uuid4())
    args: dict[str, object] = {
        "id": uuid.uuid4(),
        "site_id": "site",
        "status": "open",
        "revision": 1,
        "start_ts": NOW,
        "end_ts": NOW,
        "max_severity": "high",
        "camera_ids": ["cam01"],
        "event_types": ["intrusion"],
        "event_ids": [event],
        "members": [{"event_id": event}],
        "merged_into": None,
        "publish_pending": True,
        "created_at": NOW,
    }
    return CorrelationGroup(**(args | kw))


async def _exercise(dsn: str) -> None:
    engine = create_async_engine(dsn)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def rejected(*rows: object) -> bool:
        async with factory() as session:
            session.add_all(rows)
            try:
                await session.commit()
            except IntegrityError:
                return True
            return False

    try:
        keeper = _group()
        async with factory() as session:
            session.add(keeper)
            await session.commit()

        assert await rejected(_group(status="paused"))
        assert await rejected(_group(max_severity="meh"))
        assert await rejected(_group(revision=0))
        assert await rejected(_group(end_ts=datetime(2026, 10, 5, 10, 0, tzinfo=UTC)))
        assert await rejected(_group(status="merged", merged_into=None)), "merged needs a survivor"
        assert await rejected(_group(status="open", merged_into=keeper.id)), "only merged has one"
        assert await rejected(_group(event_ids=[], members=[])), "a group holds an event"
        assert await rejected(_group(merged_into=uuid.uuid4(), status="merged")), "unknown survivor"
        assert not await rejected(_group(status="merged", merged_into=keeper.id))  # legitimate

        def link(**kw: object) -> CorrelationLinkRow:
            args: dict[str, object] = {
                "group_id": keeper.id,
                "from_event": "e1",
                "to_event": "e2",
                "edge_type": "transit",
                "delta_s": 23.0,
                "score": 0.54,
            }
            return CorrelationLinkRow(**(args | kw))

        assert not await rejected(link())
        assert await rejected(link()), "the same pair twice"
        assert await rejected(link(from_event="x", edge_type="teleport"))
        assert await rejected(link(from_event="y", score=1.5))
        assert await rejected(link(from_event="z", score=-0.1))
        assert await rejected(link(from_event="w", group_id=uuid.uuid4())), "unknown group"
        assert not await rejected(
            link(from_event="e2", to_event="e1")
        )  # the reverse is a different row

        # which group holds this event? (the idempotency lookup, served by the GIN index)
        async with factory() as session:
            found = await session.execute(
                text("SELECT id FROM events.correlation_groups WHERE event_ids @> ARRAY[:e]"),
                {"e": keeper.event_ids[0]},
            )
            assert [r[0] for r in found] == [keeper.id]

        # deleting a group takes its links with it — and the groups that were merged into it
        async with factory() as session:
            merged_count = (
                await session.execute(
                    text("SELECT count(*) FROM events.correlation_groups WHERE merged_into = :g"),
                    {"g": keeper.id},
                )
            ).scalar_one()
        assert merged_count == 1
        async with factory() as session:
            await session.delete(await session.get(CorrelationGroup, keeper.id))
            await session.commit()
            left = (
                await session.execute(text("SELECT count(*) FROM events.correlation_links"))
            ).scalar_one()
        assert left == 0
        async with factory() as session:
            everything = (
                await session.execute(text("SELECT count(*) FROM events.correlation_groups"))
            ).scalar_one()
        assert everything == 0  # the merged group went with its survivor
    finally:
        await engine.dispose()
