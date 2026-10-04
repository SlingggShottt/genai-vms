"""Postgres side of reasoning: the job queue (`FOR UPDATE SKIP LOCKED`), the events and groups a
job is about, the segments that cover its window, and the incident rows."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vms_common.ids import uuid7_str

SEVERITY_ORDER = ("low", "medium", "high", "critical")


@dataclass(frozen=True)
class JobRow:
    id: uuid.UUID
    group_id: uuid.UUID | None
    event_ids: list[str]
    trigger: str


@dataclass(frozen=True)
class EventInfo:
    id: str
    camera_id: str
    event_type: str
    severity: str
    rule_id: str
    zone_name: str | None
    start: datetime
    end: datetime
    status: str
    caption: str | None
    confidence: float | None


@dataclass(frozen=True)
class SegmentInfo:
    segment_id: str
    twin_uri: str
    start: datetime
    end: datetime


def _now() -> datetime:
    return datetime.now(UTC)


class ReasoningStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    # --- queue --------------------------------------------------------------------------

    async def enqueue(
        self,
        *,
        group_id: uuid.UUID | None,
        event_ids: list[str],
        trigger: str,
        requested_by: uuid.UUID | None = None,
    ) -> uuid.UUID | None:
        """Queue a job; None when a live job for this group already exists."""
        job_id = uuid.UUID(uuid7_str())
        async with self._sessions() as s, s.begin():
            row = (
                await s.execute(
                    text(
                        "INSERT INTO reasoning.jobs (id, group_id, event_ids, trigger, "
                        "requested_by) VALUES (:id, :g, :e, :t, :u) ON CONFLICT DO NOTHING "
                        "RETURNING id"
                    ),
                    {"id": job_id, "g": group_id, "e": event_ids, "t": trigger, "u": requested_by},
                )
            ).first()
        return row[0] if row else None

    async def claim(self, lease_s: float) -> JobRow | None:
        async with self._sessions() as s, s.begin():
            row = (
                await s.execute(
                    text(
                        "UPDATE reasoning.jobs SET status = 'running', stage = 'starting', "
                        "started_at = coalesce(started_at, now()), locked_until = :until "
                        "WHERE id = (SELECT id FROM reasoning.jobs WHERE status = 'queued' "
                        "OR (status = 'running' AND locked_until < now()) "
                        "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1) "
                        "RETURNING id, group_id, event_ids, trigger"
                    ),
                    {"until": _now() + timedelta(seconds=lease_s)},
                )
            ).first()
        return JobRow(row[0], row[1], list(row[2] or []), row[3]) if row else None

    async def progress(
        self, job_id: uuid.UUID, stage: str, fraction: float, *, lease_s: float
    ) -> None:
        async with self._sessions() as s, s.begin():
            await s.execute(
                text(
                    "UPDATE reasoning.jobs SET stage = :st, progress = :p, locked_until = :u "
                    "WHERE id = :id"
                ),
                {
                    "id": job_id,
                    "st": stage,
                    "p": round(fraction, 3),
                    "u": _now() + timedelta(seconds=lease_s),
                },
            )

    async def attach_incident(self, job_id: uuid.UUID, incident_id: uuid.UUID) -> None:
        async with self._sessions() as s, s.begin():
            await s.execute(
                text("UPDATE reasoning.jobs SET incident_id = :i WHERE id = :id"),
                {"id": job_id, "i": incident_id},
            )

    async def finish(self, job_id: uuid.UUID, *, failed: str | None = None) -> None:
        async with self._sessions() as s, s.begin():
            await s.execute(
                text(
                    "UPDATE reasoning.jobs SET status = :st, stage = :stage, progress = :p, "
                    "error = :err, finished_at = now(), locked_until = NULL WHERE id = :id"
                ),
                {
                    "id": job_id,
                    "st": "failed" if failed else "done",
                    "stage": "failed" if failed else "done",
                    "p": 1.0,
                    "err": failed,
                },
            )

    async def auto_jobs_since(self, since: datetime) -> int:
        async with self._sessions() as s:
            return (
                await s.execute(
                    text(
                        "SELECT count(*) FROM reasoning.jobs WHERE trigger = 'auto' "
                        "AND created_at >= :since"
                    ),
                    {"since": since},
                )
            ).scalar_one()

    async def group_has_incident(self, group_id: uuid.UUID) -> bool:
        async with self._sessions() as s:
            return (
                await s.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM reasoning.incidents WHERE group_id = :g "
                        "AND status <> 'failed')"
                    ),
                    {"g": group_id},
                )
            ).scalar_one()

    # --- what a job is about ------------------------------------------------------------

    async def load_events(self, event_ids: list[str]) -> list[EventInfo]:
        if not event_ids:
            return []
        async with self._sessions() as s:
            rows = await s.execute(
                text(
                    "SELECT id::text, camera_id, event_type, severity, rule_id, zone_name, "
                    "start_ts, end_ts, status, verification->>'caption', "
                    "(verification->>'confidence')::float FROM events.events "
                    "WHERE id::text = ANY(:ids) AND status <> 'rejected' ORDER BY start_ts"
                ),
                {"ids": event_ids},
            )
            return [EventInfo(*r) for r in rows]

    async def group_event_ids(self, group_id: uuid.UUID) -> list[str]:
        async with self._sessions() as s:
            row = (
                await s.execute(
                    text("SELECT event_ids FROM events.correlation_groups WHERE id = :g"),
                    {"g": group_id},
                )
            ).first()
            return list(row[0]) if row else []

    async def group_of_event(self, event_id: str) -> uuid.UUID | None:
        """The group that holds `event_id` now, following merges."""
        async with self._sessions() as s:
            row = (
                await s.execute(
                    text(
                        "SELECT id FROM events.correlation_groups WHERE status <> 'merged' "
                        "AND :e = ANY(event_ids) ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"e": event_id},
                )
            ).first()
            return row[0] if row else None

    async def segments(self, camera_id: str, start: datetime, end: datetime) -> list[SegmentInfo]:
        async with self._sessions() as s:
            rows = await s.execute(
                text(
                    "SELECT segment_id, twin_uri, start_ts, end_ts FROM media.segments "
                    "WHERE camera_id = :c AND end_ts >= :a AND start_ts <= :b ORDER BY start_ts"
                ),
                {"c": camera_id, "a": start, "b": end},
            )
            return [SegmentInfo(*r) for r in rows]

    # --- incidents ----------------------------------------------------------------------

    async def create_incident(
        self,
        *,
        incident_id: uuid.UUID,
        job_id: uuid.UUID,
        group_id: uuid.UUID | None,
        event_ids: list[str],
        severity: str,
        event_type: str,
        title: str,
        camera_ids: list[str],
        window_start: datetime,
        window_end: datetime,
    ) -> None:
        async with self._sessions() as s, s.begin():
            await s.execute(
                text(
                    "INSERT INTO reasoning.incidents (id, job_id, group_id, event_ids, status, "
                    "severity, event_type, title, camera_ids, window_start, window_end) VALUES "
                    "(:id, :job, :g, :e, 'generating', :sev, :et, :title, :cams, :ws, :we)"
                ),
                {
                    "id": incident_id,
                    "job": job_id,
                    "g": group_id,
                    "e": event_ids,
                    "sev": severity,
                    "et": event_type,
                    "title": title,
                    "cams": camera_ids,
                    "ws": window_start,
                    "we": window_end,
                },
            )

    async def complete_incident(
        self,
        incident_id: uuid.UUID,
        *,
        status: str,
        title: str | None,
        report: dict | None,
        evidence: dict | None,
        provenance: dict,
        raw_output: str | None,
    ) -> None:
        import json

        async with self._sessions() as s, s.begin():
            await s.execute(
                text(
                    "UPDATE reasoning.incidents SET status = :st, "
                    "title = coalesce(:title, title), report = CAST(:report AS jsonb), "
                    "evidence = CAST(:evidence AS jsonb), provenance = CAST(:prov AS jsonb), "
                    "raw_output = :raw, updated_at = now() WHERE id = :id"
                ),
                {
                    "id": incident_id,
                    "st": status,
                    "title": title,
                    "report": json.dumps(report) if report is not None else None,
                    "evidence": json.dumps(evidence) if evidence is not None else None,
                    "prov": json.dumps(provenance),
                    "raw": raw_output,
                },
            )
