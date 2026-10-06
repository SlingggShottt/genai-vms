"""Postgres side of retrieval: which twin belongs to a segment, which verified events overlap a
window (and their VLM captions), full-text search over those captions, the zone vocabulary, and
the search log."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vms_db.models import SearchLog

from retrieval.domain.fusion import Hit


def _ms(ts: datetime) -> int:
    return int(ts.timestamp() * 1000)


def _utc(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


class Catalog:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """The session factory, for modules that run their own small queries (JIT cache)."""
        return self._sessions

    async def known_zones(self) -> list[str]:
        async with self._sessions() as s:
            rows = await s.execute(
                text(
                    "SELECT DISTINCT z FROM vision.track_segments, unnest(zones_visited) AS z "
                    "UNION SELECT name FROM core.zones"
                )
            )
            return sorted(r[0] for r in rows if r[0])

    async def camera_codes(self) -> list[str]:
        async with self._sessions() as s:
            rows = await s.execute(
                text("SELECT code FROM core.cameras WHERE enabled ORDER BY code")
            )
            return [r[0] for r in rows]

    async def incident_brief(self, incident_id: str) -> dict | None:
        async with self._sessions() as s:
            row = (
                await s.execute(
                    text(
                        "SELECT title, coalesce(report->>'summary', ''), event_type "
                        "FROM reasoning.incidents WHERE id::text = :i "
                        "AND status IN ('generated', 'reviewed', 'closed')"
                    ),
                    {"i": incident_id},
                )
            ).first()
        return {"title": row[0], "summary": row[1], "event_type": row[2]} if row else None

    async def twin_uris(self, segment_ids: list[str]) -> dict[str, str]:
        if not segment_ids:
            return {}
        async with self._sessions() as s:
            rows = await s.execute(
                text(
                    "SELECT segment_id, twin_uri FROM media.segments WHERE segment_id = ANY(:ids)"
                ),
                {"ids": segment_ids},
            )
            return {r[0]: r[1] for r in rows}

    async def events_in(
        self, camera_id: str, start_ms: int, end_ms: int, *, pad_s: float = 5.0
    ) -> list[dict]:
        async with self._sessions() as s:
            rows = await s.execute(
                text(
                    "SELECT id::text, event_type, severity, status, start_ts, end_ts, "
                    "verification->>'caption' AS caption "
                    "FROM events.events WHERE camera_id = :cam AND status <> 'rejected' "
                    "AND start_ts <= :hi AND end_ts >= :lo ORDER BY start_ts"
                ),
                {
                    "cam": camera_id,
                    "lo": _utc(start_ms - int(pad_s * 1000)),
                    "hi": _utc(end_ms + int(pad_s * 1000)),
                },
            )
            return [dict(r._mapping) for r in rows]

    async def event_hits(
        self,
        query: str,
        *,
        cameras: list[str],
        start: datetime | None,
        end: datetime | None,
        event_types: list[str],
        limit: int,
    ) -> list[Hit]:
        """Verified events whose caption/type matches the text (stand-in for the `knowledge`
        collection: Postgres full-text on the VLM's one-sentence caption)."""
        clauses = ["status <> 'rejected'"]
        params: dict[str, object] = {"q": query, "limit": limit}
        if cameras:
            clauses.append("camera_id = ANY(:cams)")
            params["cams"] = cameras
        if start:
            clauses.append("end_ts >= :start")
            params["start"] = start
        if end:
            clauses.append("start_ts <= :end")
            params["end"] = end
        doc = (
            "coalesce(verification->>'caption','') || ' ' || event_type || ' ' "
            "|| coalesce(zone_name,'')"
        )
        tsv = f"to_tsvector('english', {doc})"
        tsq = "websearch_to_tsquery('english', :q)"
        if event_types:
            params["types"] = event_types
        type_match = "event_type = ANY(:types)" if event_types else "false"
        # Only constant fragments are formatted in; every value is a bind parameter.
        where = " AND ".join(clauses)
        sql = (
            "SELECT id::text, camera_id, event_type, start_ts, end_ts, segment_ids, "  # noqa: S608
            "keyframe_uris, track_ids, zone_name, verification->>'caption' AS caption, "
            f"ts_rank({tsv}, {tsq}) AS rank, ({type_match}) AS type_hit "
            f"FROM events.events WHERE {where} AND ({tsv} @@ {tsq} OR {type_match}) "
            "ORDER BY type_hit DESC, rank DESC, start_ts DESC LIMIT :limit"
        )
        async with self._sessions() as s:
            rows = await s.execute(text(sql), params)
            out: list[Hit] = []
            for r in rows:
                m = r._mapping
                out.append(
                    Hit(
                        source="events",
                        key=f"e:{m['id']}",
                        camera_id=m["camera_id"],
                        start_ms=_ms(m["start_ts"]),
                        end_ms=_ms(m["end_ts"]),
                        cosine=float(m["rank"] or 0),
                        segment_ids=list(m["segment_ids"] or []),
                        keyframe_uri=(m["keyframe_uris"] or [None])[0],
                        event_id=m["id"],
                        caption=m["caption"],
                        zones=[m["zone_name"]] if m["zone_name"] else [],
                        boost=1.3 if m["type_hit"] else 1.0,
                    )
                )
            return out

    async def log_search(
        self,
        *,
        search_id: str,
        user_id: str | None,
        kind: str,
        query: str,
        mode: str,
        profile: str,
        plan: dict | None,
        results: list[dict],
        timings: dict[str, float],
    ) -> None:
        async with self._sessions() as s, s.begin():
            s.add(
                SearchLog(
                    id=uuid.UUID(search_id),
                    user_id=uuid.UUID(user_id) if user_id else None,
                    kind=kind,
                    query=query,
                    mode=mode,
                    profile=profile,
                    plan=plan,
                    results=results,
                    timings=timings,
                )
            )
