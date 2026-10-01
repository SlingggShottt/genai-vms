"""Idempotent writes of rule-engine candidates into `events.candidates` (P3-D1).

Every write is an upsert on the deterministic candidate id, so redelivering a
`twinready.v1` (Kafka is at-least-once) leaves the same rows, never duplicates
(CLAUDE.md: Kafka consumers do an idempotent write). Merging is monotonic, so
the result doesn't depend on the order updates arrive in:

* `end_ts`, `rule_score`: the greater value;
* `track_ids`, `segment_ids`: the sorted union;
* `status`: `closed` is final — a late replay of an `open` update can't reopen it;
* `details`: from whichever update reaches furthest in time.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from events.domain.candidates import CandidateUpdate

# `RETURNING (xmax = 0)` is the standard Postgres idiom for "this row was inserted,
# not updated" under ON CONFLICT DO UPDATE.
_UPSERT_SQL = text(
    """
    INSERT INTO events.candidates
        (id, site_id, camera_id, rule_id, event_type, severity, zone_id, zone_name,
         track_ids, segment_ids, start_ts, end_ts, rule_score, status, details)
    VALUES
        (:id, :site_id, :camera_id, :rule_id, :event_type, :severity, :zone_id, :zone_name,
         :track_ids, :segment_ids, :start_ts, :end_ts, :rule_score, :status,
         CAST(:details AS jsonb))
    ON CONFLICT (id) DO UPDATE SET
        end_ts = GREATEST(events.candidates.end_ts, excluded.end_ts),
        track_ids = ARRAY(
            SELECT DISTINCT t
            FROM unnest(events.candidates.track_ids || excluded.track_ids) AS t
            ORDER BY t),
        segment_ids = ARRAY(
            SELECT DISTINCT s
            FROM unnest(events.candidates.segment_ids || excluded.segment_ids) AS s
            ORDER BY s),
        rule_score = GREATEST(events.candidates.rule_score, excluded.rule_score),
        status = CASE WHEN events.candidates.status = 'closed'
                      THEN 'closed' ELSE excluded.status END,
        details = CASE WHEN excluded.end_ts >= events.candidates.end_ts
                       THEN excluded.details ELSE events.candidates.details END,
        updated_at = now()
    RETURNING (xmax = 0) AS inserted
    """
)


async def upsert_candidates(
    session: AsyncSession, updates: Sequence[CandidateUpdate]
) -> list[CandidateUpdate]:
    """Upsert `updates`; return the ones that created a new row.

    Call inside one transaction (`vms_db.session.session_scope`) so a batch is
    all-or-nothing.
    """
    created: list[CandidateUpdate] = []
    for update in updates:
        result = await session.execute(
            _UPSERT_SQL,
            {
                "id": update.id,
                "site_id": update.site_id,
                "camera_id": update.camera_id,
                "rule_id": update.rule_id,
                "event_type": update.event_type,
                "severity": update.severity,
                "zone_id": update.zone_id,
                "zone_name": update.zone_name,
                "track_ids": update.track_ids,
                "segment_ids": update.segment_ids,
                "start_ts": update.start_ts,
                "end_ts": update.end_ts,
                "rule_score": update.rule_score,
                "status": update.status,
                "details": json.dumps(update.details),
            },
        )
        if result.scalar_one():
            created.append(update)
    return created
