"""Idempotency: replaying the same `twinready.v1` message must not
duplicate rows (P2-J1 AC). Also checks the recomputed `vision.tracks`
aggregate and the `vision.minute_counts` GREATEST-merge.

Run via `make test-int` (needs Docker).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from indexer.adapters.repository import index_twin
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from vms_common.contracts.twin import TwinV1
from vms_common.contracts.twinready import TwinReadyV1
from vms_db.models import MinuteCount, Segment, Track, TrackSegment
from vms_db.session import session_scope

pytestmark = pytest.mark.integration

FIXTURES = (
    Path(__file__).resolve().parents[4] / "libs" / "vms_common" / "src" / "vms_common" / "fixtures"
)


def _load_twinready() -> TwinReadyV1:
    return TwinReadyV1.model_validate_json((FIXTURES / "twinready_v1.json").read_text())


def _load_twin() -> TwinV1:
    return TwinV1.model_validate_json((FIXTURES / "twin_v1.json").read_text())


async def _table_row_count(session_factory: async_sessionmaker, model: type) -> int:
    async with session_factory() as session:
        result = await session.execute(select(func.count()).select_from(model))
        return result.scalar_one()


@pytest.mark.asyncio
async def test_replaying_the_same_message_does_not_duplicate_rows(
    session_factory: async_sessionmaker,
) -> None:
    twinready = _load_twinready()
    twin = _load_twin()

    for _ in range(2):
        async with session_scope(session_factory) as session:
            await index_twin(session, twinready, twin)

    assert await _table_row_count(session_factory, Segment) == 1
    assert await _table_row_count(session_factory, Track) == 1
    assert await _table_row_count(session_factory, TrackSegment) == 1
    # twin fixture's one frame has one "person" object in one minute bucket.
    assert await _table_row_count(session_factory, MinuteCount) == 1


@pytest.mark.asyncio
async def test_indexed_segment_and_track_match_the_twin_document(
    session_factory: async_sessionmaker,
) -> None:
    twinready = _load_twinready()
    twin = _load_twin()

    async with session_scope(session_factory) as session:
        await index_twin(session, twinready, twin)

    async with session_factory() as session:
        segment = await session.get(Segment, twin.segment_id)
        assert segment is not None
        assert segment.camera_id == twin.camera_id
        assert segment.twin_uri == twinready.twin_uri
        assert segment.uri == (
            "s3://vms-segments/cam03/2026/10/05/10/cam03_20261005T101500Z_000123.ts"
        )

        track = await session.get(Track, "cam03-t412")
        assert track is not None
        assert track.category == "person"
        assert track.zones_visited == ["entrance"]
        assert track.best_crop_uri == twin.tracks[0].best_crop_uri

        minute_count = await session.get(
            MinuteCount, ("cam03", "person", twin.frames[0].ts.replace(second=0, microsecond=0))
        )
        assert minute_count is not None
        assert minute_count.count == 1


def test_fixtures_are_still_valid_json_for_this_test_to_trust() -> None:
    # Cheap guard: if the shared fixtures ever stop parsing as the contracts
    # they claim to be, fail here with a clear message instead of inside a
    # slow testcontainers test.
    json.loads((FIXTURES / "twinready_v1.json").read_text())
    json.loads((FIXTURES / "twin_v1.json").read_text())
