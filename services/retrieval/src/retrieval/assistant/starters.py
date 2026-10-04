"""Starter questions for an empty conversation, drawn from the last 24 hours of the archive
(FR-AST-01): they only offer what there is something to find for."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

GENERIC = [
    "Find a person carrying a backpack",
    "What can you tell me about the footage?",
]


async def starters(sessions: async_sessionmaker[AsyncSession]) -> list[str]:
    since = datetime.now(UTC) - timedelta(hours=24)
    out: list[str] = []
    async with sessions() as s:
        ev = (
            await s.execute(
                text(
                    "SELECT event_type, camera_id, count(*) FROM events.events "
                    "WHERE status <> 'rejected' AND start_ts >= :t GROUP BY 1, 2 "
                    "ORDER BY 3 DESC LIMIT 2"
                ),
                {"t": since},
            )
        ).all()
        inc = (
            await s.execute(
                text(
                    "SELECT count(*) FROM reasoning.incidents WHERE created_at >= :t "
                    "AND status IN ('generated','reviewed','closed')"
                ),
                {"t": since},
            )
        ).scalar_one()
        cam = (
            await s.execute(
                text(
                    "SELECT camera_id FROM vision.minute_counts WHERE minute_ts >= :t "
                    "GROUP BY 1 ORDER BY count(*) DESC LIMIT 1"
                ),
                {"t": since},
            )
        ).scalar()
    if ev:
        out.append(f"What happened on {ev[0][1]} in the last 24 hours?")
        out.append(f"Were there any {ev[0][0].replace('_', ' ')} events today?")
    if inc:
        out.append("Summarise today's incident reports")
    if cam:
        out.append(f"How many people were on {cam} at the busiest time today?")
    return (out + GENERIC)[:5]
