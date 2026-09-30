"""Integration test: apply the full Alembic history to a throwaway Postgres
container and assert the `media`/`vision` schema/tables/constraints from
migration 0002 land as designed (P2-J1 AC: "Migrations for media.* and
vision.*").

Run via `make test-int` (needs Docker).
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer
from vms_db.models import MinuteCount, Segment, Track, TrackSegment

pytestmark = pytest.mark.integration

VMS_DB_ROOT = Path(__file__).resolve().parents[2]


def _async_dsn(container: PostgresContainer) -> str:
    return container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


# See test_migrations.py's matching note: `command.upgrade` drives our async
# `migrations/env.py` via its own `asyncio.run(...)`, so this test stays sync.
def test_migration_0002_creates_media_vision_schema_tables_and_constraints() -> None:
    with PostgresContainer("postgres:16-alpine") as pg:
        dsn = _async_dsn(pg)
        os.environ["VMS_DB_DSN"] = dsn
        try:
            alembic_cfg = Config(str(VMS_DB_ROOT / "alembic.ini"))
            command.upgrade(alembic_cfg, "head")

            info = asyncio.run(_inspect_schemas(dsn))
            asyncio.run(_round_trip_insert(dsn))
        finally:
            os.environ.pop("VMS_DB_DSN", None)

    assert info["schemas"] >= {"media", "vision"}
    assert info["media_tables"] == {"segments"}
    assert info["vision_tables"] == {"tracks", "track_segments", "minute_counts"}


async def _inspect_schemas(dsn: str) -> dict:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:

            def _sync_inspect(sync_conn):
                inspector = inspect(sync_conn)
                return {
                    "schemas": set(inspector.get_schema_names()),
                    "media_tables": set(inspector.get_table_names(schema="media")),
                    "vision_tables": set(inspector.get_table_names(schema="vision")),
                }

            return await conn.run_sync(_sync_inspect)
    finally:
        await engine.dispose()


async def _round_trip_insert(dsn: str) -> None:
    """A migrated schema must accept the rows the ORM models will write,
    including the FKs `track_segments` holds to both `segments` and `tracks`.
    """
    engine = create_async_engine(dsn)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    try:
        async with session_factory() as session:
            session.add(
                Segment(
                    segment_id="cam01_20260929T101500Z_000001",
                    camera_id="cam01",
                    site_id="rvce-campus",
                    start_ts=now,
                    end_ts=now,
                    uri="s3://vms-segments/cam01/2026/09/29/10/cam01_20260929T101500Z_000001.ts",
                    twin_uri="s3://vms-twins/cam01/2026/09/29/10/cam01_20260929T101500Z_000001.json",
                    perception_version="yolo11s-bytetrack-siglip2b@0.1.0",
                )
            )
            session.add(
                Track(
                    track_id="cam01-t1",
                    camera_id="cam01",
                    category="person",
                    first_ts=now,
                    last_ts=now,
                    zones_visited=["entrance"],
                    attributes_summary={"upper_color": "red"},
                    best_crop_uri="s3://vms-crops/cam01/t1.jpg",
                )
            )
            await session.flush()

            session.add(
                TrackSegment(
                    track_id="cam01-t1",
                    segment_id="cam01_20260929T101500Z_000001",
                    camera_id="cam01",
                    first_ts=now,
                    last_ts=now,
                    dwell_s=3.5,
                    zones_visited=["entrance"],
                    attributes_summary={"upper_color": "red"},
                    best_crop_uri="s3://vms-crops/cam01/t1.jpg",
                    embedding_index=0,
                )
            )
            session.add(
                MinuteCount(
                    camera_id="cam01",
                    category="person",
                    minute_ts=now.replace(second=0, microsecond=0),
                    site_id="rvce-campus",
                    count=2,
                )
            )
            await session.commit()

            refreshed = await session.get(
                TrackSegment, ("cam01-t1", "cam01_20260929T101500Z_000001")
            )
            assert refreshed is not None
            assert refreshed.dwell_s == 3.5
    finally:
        await engine.dispose()
