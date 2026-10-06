"""Daily security report generation (P6-J1): figures → narrative → stored report.

`generate` is what the worker runs for a queued `reasoning.daily_reports` row. The narrative is
asked of `daily_narrative`; every number in it must appear in the figures, otherwise the model
gets one more try and then the template text is used instead (and `narrative_source` says so).

    python -m reasoning.reports.daily --date yesterday      # queue a report
    python -m reasoning.reports.daily --from 2026-10-01 --to 2026-10-03
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vms_common.ids import uuid7_str
from vms_common.llm import Gateway, LLMError, render_prompt
from vms_common.logging import get_logger

from reasoning.metrics import daily_reports_total
from reasoning.reports.facts import (
    DailyFacts,
    collect,
    figures_text,
    period_label,
    template_narrative,
    unsupported_numbers,
)

log = get_logger(__name__)

PROMPT_VERSION = "1.0"
MAX_DAYS = 7


async def narrate(gateway: Gateway, facts: DailyFacts) -> tuple[str, str]:
    """(narrative, source) where source is `llm` or `template`."""
    prompt = render_prompt(
        "daily_narrative", PROMPT_VERSION, period=period_label(facts), facts=figures_text(facts)
    )
    for attempt in (1, 2):
        try:
            result = await gateway.chat("daily_narrative", [{"role": "user", "content": prompt}])
        except LLMError as exc:
            log.warning("daily_narrative_unavailable", error=str(exc))
            break
        narrative = result.text.strip()
        bad = unsupported_numbers(narrative, facts)
        if narrative and not bad:
            return narrative, "llm"
        log.info("daily_narrative_rejected", attempt=attempt, unsupported=bad)
        prompt += (
            f"\n\nYour previous text used numbers that are not in the figures ({', '.join(bad)}). "
            "Write it again using only numbers that appear in the figures."
        )
    return template_narrative(facts), "template"


async def generate(
    sessions: async_sessionmaker[AsyncSession],
    gateway: Gateway,
    report_id: uuid.UUID,
    tz: ZoneInfo,
) -> None:
    async with sessions() as s:
        row = (
            await s.execute(
                text("SELECT date_from, date_to FROM reasoning.daily_reports WHERE id = :i"),
                {"i": report_id},
            )
        ).one()
    facts = await collect(sessions, row[0], row[1], tz)
    narrative, source = await narrate(gateway, facts)
    async with sessions() as s, s.begin():
        await s.execute(
            text(
                "UPDATE reasoning.daily_reports SET status = 'ready', facts = CAST(:f AS jsonb), "
                "narrative = :n, narrative_source = :src, finished_at = now(), "
                "locked_until = NULL, error = NULL WHERE id = :i"
            ),
            {"i": report_id, "f": facts.model_dump_json(), "n": narrative, "src": source},
        )
    daily_reports_total.labels(narrative=source).inc()
    log.info("daily_report_ready", report_id=str(report_id), source=source)


class ReportQueue:
    """Claim and queue report rows (the same `SKIP LOCKED` pattern as jobs)."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], lease_s: float) -> None:
        self._sessions = sessions
        self._lease_s = lease_s

    async def enqueue(
        self, date_from: date, date_to: date, requested_by: uuid.UUID | None = None
    ) -> uuid.UUID:
        rid = uuid.UUID(uuid7_str())
        async with self._sessions() as s, s.begin():
            await s.execute(
                text(
                    "INSERT INTO reasoning.daily_reports (id, date_from, date_to, requested_by) "
                    "VALUES (:i, :a, :b, :u)"
                ),
                {"i": rid, "a": date_from, "b": date_to, "u": requested_by},
            )
        return rid

    async def claim(self) -> uuid.UUID | None:
        async with self._sessions() as s, s.begin():
            row = (
                await s.execute(
                    text(
                        "UPDATE reasoning.daily_reports SET status = 'generating', "
                        "locked_until = :u WHERE id = (SELECT id FROM reasoning.daily_reports "
                        "WHERE status = 'queued' "
                        "OR (status = 'generating' AND locked_until < now()) "
                        "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING id"
                    ),
                    {"u": datetime.now(UTC) + timedelta(seconds=self._lease_s)},
                )
            ).first()
        return row[0] if row else None

    async def fail(self, report_id: uuid.UUID, reason: str) -> None:
        async with self._sessions() as s, s.begin():
            await s.execute(
                text(
                    "UPDATE reasoning.daily_reports SET status = 'failed', error = :e, "
                    "finished_at = now(), locked_until = NULL WHERE id = :i"
                ),
                {"i": report_id, "e": reason[:500]},
            )

    async def scheduled_exists(self, day: date) -> bool:
        async with self._sessions() as s:
            return (
                await s.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM reasoning.daily_reports WHERE date_from = :d "
                        "AND date_to = :d AND status <> 'failed')"
                    ),
                    {"d": day},
                )
            ).scalar_one()


def yesterday(tz: ZoneInfo) -> date:
    return datetime.now(tz).date() - timedelta(days=1)


async def _cli() -> None:
    from vms_db.session import create_engine, create_session_factory

    from reasoning.settings import ReasoningSettings

    parser = argparse.ArgumentParser(description="Queue a daily security report")
    parser.add_argument("--date", help="YYYY-MM-DD, 'today' or 'yesterday'")
    parser.add_argument("--from", dest="date_from")
    parser.add_argument("--to", dest="date_to")
    args = parser.parse_args()
    settings = ReasoningSettings()
    tz = ZoneInfo(settings.site_timezone)
    today = datetime.now(tz).date()
    named = {"today": today, "yesterday": today - timedelta(days=1)}

    def parse(v: str) -> date:
        return named.get(v) or date.fromisoformat(v)

    if args.date:
        a = b = parse(args.date)
    elif args.date_from and args.date_to:
        a, b = parse(args.date_from), parse(args.date_to)
    else:
        parser.error("give --date, or --from and --to")
    if b < a or (b - a).days + 1 > MAX_DAYS:
        parser.error(f"the range must run forwards and span at most {MAX_DAYS} days")
    engine = create_engine(settings.db)
    try:
        rid = await ReportQueue(create_session_factory(engine), settings.job_lease_s).enqueue(a, b)
        print(f"queued report {rid} for {a} to {b}; the reasoning worker will write it")  # noqa: T201
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_cli())
