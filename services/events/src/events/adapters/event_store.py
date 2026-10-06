"""The VLM gate's work queue and outbox in Postgres (P3-D4).

* **Queue** — a candidate is waiting while no `events.events` row has its id. `claim` takes a
  few of them under `FOR UPDATE SKIP LOCKED` (two replicas never share one) and pushes
  `verify_not_before` out by the lease, which both hides the candidate while it is being judged
  and, if the worker dies, makes it come back. `reschedule` sets a back-off instead.
* **Decisions** — `save_event` writes the event row once: its id is the candidate's, so a
  retried verification cannot produce a second row.
* **Outbox** — a verified/skipped row with no `published_at` is waiting to be sent as `event.v1`;
  `unpublished` lists them and `mark_published` ticks one off after the send, so a crash between
  the insert and the send loses nothing (it is sent again, and consumers ignore a duplicate).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from vms_db.session import session_scope

from events.domain.records import EventRow, PendingCandidate

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

_CLAIM_SQL = text(
    """
    WITH due AS (
        SELECT c.id
        FROM events.candidates c
        WHERE NOT EXISTS (SELECT 1 FROM events.events e WHERE e.id = c.id)
          AND (c.status = 'closed' OR c.created_at <= :open_cutoff)
          AND (c.verify_not_before IS NULL OR c.verify_not_before <= :now)
          AND c.end_ts >= :age_cutoff
        ORDER BY CASE c.severity
                     WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3
                 END,
                 c.end_ts
        LIMIT :limit
        FOR UPDATE OF c SKIP LOCKED
    )
    UPDATE events.candidates c
    SET verify_attempts = c.verify_attempts + 1,
        verify_first_at = COALESCE(c.verify_first_at, :now),
        verify_not_before = :lease_until
    FROM due
    WHERE c.id = due.id
    RETURNING c.id, c.site_id, c.camera_id, c.rule_id, c.event_type, c.severity, c.zone_id,
              c.zone_name, c.track_ids, c.segment_ids, c.start_ts, c.end_ts, c.rule_score,
              c.status, c.details, c.verify_attempts, c.verify_first_at
    """
)

_SAVE_SQL = text(
    """
    INSERT INTO events.events
        (id, site_id, camera_id, event_type, severity, rule_id, rule_score, zone_id, zone_name,
         track_ids, segment_ids, keyframe_uris, start_ts, end_ts, status, verification)
    VALUES
        (:id, :site_id, :camera_id, :event_type, :severity, :rule_id, :rule_score, :zone_id,
         :zone_name, :track_ids, :segment_ids, :keyframe_uris, :start_ts, :end_ts, :status,
         CAST(:verification AS jsonb))
    ON CONFLICT (id) DO NOTHING
    RETURNING id
    """
)

_RESCHEDULE_SQL = text(
    "UPDATE events.candidates SET verify_not_before = :not_before WHERE id = :id"
)

_UNPUBLISHED_SQL = text(
    """
    SELECT id, site_id, camera_id, event_type, severity, rule_id, rule_score, zone_id, zone_name,
           track_ids, segment_ids, keyframe_uris, start_ts, end_ts, status, verification
    FROM events.events
    WHERE status IN ('verified', 'skipped') AND published_at IS NULL
    ORDER BY created_at
    LIMIT :limit
    """
)

_MARK_PUBLISHED_SQL = text(
    "UPDATE events.events SET published_at = :at WHERE id = :id AND published_at IS NULL"
)


class PostgresEventStore:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def claim(
        self,
        *,
        now: datetime,
        limit: int,
        lease_s: float,
        open_after_s: float,
        max_age_s: float,
    ) -> list[PendingCandidate]:
        """Up to `limit` candidates to judge now: closed ones, and ones that have been going for
        `open_after_s` (a long dwell should not wait for the person to leave), skipping any that
        ended more than `max_age_s` ago (nothing was ever going to judge those) or are leased or
        backing off. Highest severity first, then oldest."""
        async with session_scope(self._session_factory) as session:
            rows = (
                (
                    await session.execute(
                        _CLAIM_SQL,
                        {
                            "now": now,
                            "limit": limit,
                            "lease_until": now + timedelta(seconds=lease_s),
                            "open_cutoff": now - timedelta(seconds=open_after_s),
                            "age_cutoff": now - timedelta(seconds=max_age_s),
                        },
                    )
                )
                .mappings()
                .all()
            )
        claimed = [
            PendingCandidate(
                id=row["id"],
                site_id=row["site_id"],
                camera_id=row["camera_id"],
                rule_id=row["rule_id"],
                event_type=row["event_type"],
                severity=row["severity"],
                zone_id=row["zone_id"],
                zone_name=row["zone_name"],
                track_ids=list(row["track_ids"]),
                segment_ids=list(row["segment_ids"]),
                start_ts=row["start_ts"],
                end_ts=row["end_ts"],
                rule_score=row["rule_score"],
                status=row["status"],
                details=row["details"],
                attempts=row["verify_attempts"],
                first_at=row["verify_first_at"],
            )
            for row in rows
        ]
        return sorted(claimed, key=lambda c: (_SEVERITY_RANK[c.severity], c.end_ts))

    async def save_event(self, row: EventRow) -> bool:
        """Write the decision; False if the candidate already has one (nothing is changed)."""
        async with session_scope(self._session_factory) as session:
            result = await session.execute(
                _SAVE_SQL,
                {
                    "id": row.id,
                    "site_id": row.site_id,
                    "camera_id": row.camera_id,
                    "event_type": row.event_type,
                    "severity": row.severity,
                    "rule_id": row.rule_id,
                    "rule_score": row.rule_score,
                    "zone_id": row.zone_id,
                    "zone_name": row.zone_name,
                    "track_ids": row.track_ids,
                    "segment_ids": row.segment_ids,
                    "keyframe_uris": row.keyframe_uris,
                    "start_ts": row.start_ts,
                    "end_ts": row.end_ts,
                    "status": row.status,
                    "verification": json.dumps(row.verification),
                },
            )
            return result.scalar_one_or_none() is not None

    async def reschedule(self, candidate_id: uuid.UUID, not_before: datetime) -> None:
        """Do not offer this candidate to the gate again before `not_before`."""
        async with session_scope(self._session_factory) as session:
            await session.execute(_RESCHEDULE_SQL, {"id": candidate_id, "not_before": not_before})

    async def unpublished(self, *, limit: int) -> list[EventRow]:
        async with session_scope(self._session_factory) as session:
            rows = (await session.execute(_UNPUBLISHED_SQL, {"limit": limit})).mappings().all()
        return [
            EventRow(
                id=row["id"],
                site_id=row["site_id"],
                camera_id=row["camera_id"],
                event_type=row["event_type"],
                severity=row["severity"],
                rule_id=row["rule_id"],
                rule_score=row["rule_score"],
                zone_id=row["zone_id"],
                zone_name=row["zone_name"],
                track_ids=list(row["track_ids"]),
                segment_ids=list(row["segment_ids"]),
                keyframe_uris=list(row["keyframe_uris"]),
                start_ts=row["start_ts"],
                end_ts=row["end_ts"],
                status=row["status"],
                verification=row["verification"],
            )
            for row in rows
        ]

    async def mark_published(self, event_id: uuid.UUID, at: datetime) -> None:
        async with session_scope(self._session_factory) as session:
            await session.execute(_MARK_PUBLISHED_SQL, {"id": event_id, "at": at})
