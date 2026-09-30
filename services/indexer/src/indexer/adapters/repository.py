"""Idempotent writes of one twin document into `media.segments`,
`vision.tracks`, `vision.track_segments`, `vision.minute_counts` (P2-J1).

Every write is an upsert keyed so that replaying the same `twinready.v1`
message twice leaves the same rows, not duplicates (CLAUDE.md: Kafka
consumers do an idempotent write). `vision.tracks` is the one exception to
"insert-or-update the row you were given": it's fully recomputed from its
`vision.track_segments` children on every write (`_recompute_track`), which
is both idempotent under replay and order-independent under an
out-of-order segment, at the cost of one extra query per track per segment.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from vms_common.contracts.twin import TrackSummary, TwinV1
from vms_common.contracts.twinready import TwinReadyV1
from vms_db.models import Segment, Track, TrackSegment

from indexer.domain.minute_counts import compute_minute_counts
from indexer.domain.segment_key import build_segment_uri

# Recomputes `vision.tracks` from every `vision.track_segments` row for one
# track: MIN/MAX of first/last_ts, a set-union of zones_visited, and the
# most-recently-seen segment's attributes/best_crop (see module docstring
# and vms_db.models.vision.Track's docstring for why "most recent" rather
# than e.g. "largest crop" — track_segments doesn't carry crop area).
_RECOMPUTE_TRACK_SQL = text(
    """
    INSERT INTO vision.tracks
        (track_id, camera_id, category, first_ts, last_ts,
         zones_visited, attributes_summary, best_crop_uri, updated_at)
    SELECT
        ts.track_id,
        :camera_id,
        :category,
        MIN(ts.first_ts),
        MAX(ts.last_ts),
        COALESCE(
            (SELECT array_agg(DISTINCT z)
             FROM vision.track_segments t2, unnest(t2.zones_visited) AS z
             WHERE t2.track_id = :track_id),
            '{}'
        ),
        (SELECT t3.attributes_summary FROM vision.track_segments t3
         WHERE t3.track_id = :track_id ORDER BY t3.last_ts DESC LIMIT 1),
        (SELECT t4.best_crop_uri FROM vision.track_segments t4
         WHERE t4.track_id = :track_id ORDER BY t4.last_ts DESC LIMIT 1),
        now()
    FROM vision.track_segments ts
    WHERE ts.track_id = :track_id
    GROUP BY ts.track_id
    ON CONFLICT (track_id) DO UPDATE SET
        first_ts = excluded.first_ts,
        last_ts = excluded.last_ts,
        zones_visited = excluded.zones_visited,
        attributes_summary = excluded.attributes_summary,
        best_crop_uri = excluded.best_crop_uri,
        updated_at = excluded.updated_at
    """
)

# `vision.minute_counts.count` merges across the several segments that share
# a minute with GREATEST — a no-op on exact replay (same value), and stable
# regardless of processing order.
_UPSERT_MINUTE_COUNT_SQL = text(
    """
    INSERT INTO vision.minute_counts (camera_id, category, minute_ts, site_id, count)
    VALUES (:camera_id, :category, :minute_ts, :site_id, :count)
    ON CONFLICT (camera_id, category, minute_ts) DO UPDATE SET
        count = GREATEST(vision.minute_counts.count, excluded.count)
    """
)


async def index_twin(session: AsyncSession, twinready: TwinReadyV1, twin: TwinV1) -> None:
    """Upsert everything one `twinready.v1` message + its twin document
    produce. Call within a single transaction (P1-J1's `session_scope`) so a
    mid-way failure doesn't leave a segment indexed without its tracks.
    """
    await _upsert_segment(session, twinready)
    for track_summary in twin.tracks:
        await _upsert_track_placeholder(session, track_summary, camera_id=twin.camera_id)
        await _upsert_track_segment(
            session, track_summary, segment_id=twin.segment_id, camera_id=twin.camera_id
        )
        await session.execute(
            _RECOMPUTE_TRACK_SQL,
            {
                "track_id": track_summary.track_id,
                "camera_id": twin.camera_id,
                "category": track_summary.category,
            },
        )
    await _upsert_minute_counts(session, twin)


async def _upsert_segment(session: AsyncSession, twinready: TwinReadyV1) -> None:
    stmt = pg_insert(Segment).values(
        segment_id=twinready.segment_id,
        camera_id=twinready.camera_id,
        site_id=twinready.site_id,
        start_ts=twinready.start_ts,
        end_ts=twinready.end_ts,
        uri=build_segment_uri(twinready.camera_id, twinready.start_ts, twinready.segment_id),
        twin_uri=twinready.twin_uri,
        perception_version=twinready.perception_version,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Segment.segment_id],
        set_={
            "end_ts": stmt.excluded.end_ts,
            "uri": stmt.excluded.uri,
            "twin_uri": stmt.excluded.twin_uri,
            "perception_version": stmt.excluded.perception_version,
            "indexed_at": text("now()"),
        },
    )
    await session.execute(stmt)


async def _upsert_track_placeholder(
    session: AsyncSession, track_summary: TrackSummary, *, camera_id: str
) -> None:
    """Insert a minimal `vision.tracks` row if one doesn't exist yet, purely
    to satisfy `track_segments`' FK before `_RECOMPUTE_TRACK_SQL` overwrites
    it with the real aggregate. `DO NOTHING` on conflict: never regress an
    existing track's aggregated fields with one segment's local view.
    """
    stmt = pg_insert(Track).values(
        track_id=track_summary.track_id,
        camera_id=camera_id,
        category=track_summary.category,
        first_ts=track_summary.first_ts,
        last_ts=track_summary.last_ts,
        zones_visited=track_summary.zones_visited,
        attributes_summary=track_summary.attributes_summary.model_dump(exclude_none=True),
        best_crop_uri=track_summary.best_crop_uri,
    )
    stmt = stmt.on_conflict_do_nothing(index_elements=[Track.track_id])
    await session.execute(stmt)


async def _upsert_track_segment(
    session: AsyncSession, track_summary: TrackSummary, *, segment_id: str, camera_id: str
) -> None:
    stmt = pg_insert(TrackSegment).values(
        track_id=track_summary.track_id,
        segment_id=segment_id,
        camera_id=camera_id,
        first_ts=track_summary.first_ts,
        last_ts=track_summary.last_ts,
        dwell_s=track_summary.dwell_s,
        zones_visited=track_summary.zones_visited,
        attributes_summary=track_summary.attributes_summary.model_dump(exclude_none=True),
        best_crop_uri=track_summary.best_crop_uri,
        embedding_index=track_summary.embedding_index,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[TrackSegment.track_id, TrackSegment.segment_id],
        set_={
            "first_ts": stmt.excluded.first_ts,
            "last_ts": stmt.excluded.last_ts,
            "dwell_s": stmt.excluded.dwell_s,
            "zones_visited": stmt.excluded.zones_visited,
            "attributes_summary": stmt.excluded.attributes_summary,
            "best_crop_uri": stmt.excluded.best_crop_uri,
            "embedding_index": stmt.excluded.embedding_index,
        },
    )
    await session.execute(stmt)


async def _upsert_minute_counts(session: AsyncSession, twin: TwinV1) -> None:
    for key, count in compute_minute_counts(twin).items():
        await session.execute(
            _UPSERT_MINUTE_COUNT_SQL,
            {
                "camera_id": twin.camera_id,
                "category": key.category,
                "minute_ts": key.minute_ts,
                "site_id": twin.site_id,
                "count": count,
            },
        )
