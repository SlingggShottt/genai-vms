"""Integration test: migration 0015 adds `retrieval.search_logs.candidates` (P4-J4 AC), which keeps
what a search had before reranking. Run via `make test-int` (needs Docker)."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer
from vms_db.models import SearchLog

pytestmark = pytest.mark.integration

VMS_DB_ROOT = Path(__file__).resolve().parents[2]


def _async_dsn(container: PostgresContainer) -> str:
    return container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


async def _columns(dsn: str) -> set[str]:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(
                lambda c: {
                    col["name"] for col in inspect(c).get_columns("search_logs", schema="retrieval")
                }
            )
    finally:
        await engine.dispose()


async def _write_and_read(dsn: str) -> tuple[list, list]:
    engine = create_async_engine(dsn)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as s, s.begin():
            s.add(
                SearchLog(
                    id=uuid.uuid4(),
                    kind="text",
                    query="q",
                    mode="reason",
                    profile="local",
                    candidates=[{"id": "a", "camera": "cam01", "fused_score": 0.9}],
                    results=[{"id": "a", "camera": "cam01", "score": 0.4}],
                    timings={"total": 1.0},
                )
            )
            s.add(
                SearchLog(id=uuid.uuid4(), kind="image", query="img", mode="fast", profile="local")
            )
        async with sessions() as s:
            rows = (await s.execute(select(SearchLog).order_by(SearchLog.kind))).scalars().all()
            return rows[1].candidates, rows[0].candidates  # text, then image: the default
    finally:
        await engine.dispose()


def test_migration_0015_adds_the_candidates_column_and_downgrades_cleanly() -> None:
    with PostgresContainer("postgres:16-alpine") as pg:
        dsn = _async_dsn(pg)
        os.environ["VMS_DB_DSN"] = dsn
        cfg = Config(str(VMS_DB_ROOT / "alembic.ini"))
        try:
            command.upgrade(cfg, "0014")
            before = asyncio.run(_columns(dsn))
            command.upgrade(cfg, "0015")
            after = asyncio.run(_columns(dsn))
            text_candidates, default_candidates = asyncio.run(_write_and_read(dsn))
            command.downgrade(cfg, "0014")
            back = asyncio.run(_columns(dsn))
        finally:
            os.environ.pop("VMS_DB_DSN", None)

    assert "candidates" not in before and "candidates" in after and "candidates" not in back
    assert text_candidates == [{"id": "a", "camera": "cam01", "fused_score": 0.9}]
    assert default_candidates == []  # a log written without them (an image search) is an empty list
