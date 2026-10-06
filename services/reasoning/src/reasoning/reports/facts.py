"""Daily-report figures (FR-RPT-01): aggregated with fixed, parameterised SQL over a date range
in site time, and the pure helpers that turn them into text and check a narrative against them."""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class IncidentLine(BaseModel):
    id: str
    title: str
    severity: str
    event_type: str
    cameras: list[str]
    at: str  # site-time clock


class DailyFacts(BaseModel):
    """Everything the report may state. The narrative is checked against these numbers."""

    date_from: date
    date_to: date
    timezone: str
    events_total: int = 0
    events_rejected: int = 0  # candidates the vision model judged to be false alarms
    by_type: dict[str, int] = Field(default_factory=dict)
    by_camera: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_hour: dict[str, int] = Field(default_factory=dict)  # "00".."23" -> events
    incidents_total: int = 0
    incidents: list[IncidentLine] = Field(default_factory=list)
    alerts_total: int = 0
    alerts_open: int = 0
    ack_p50_s: int | None = None
    ack_p90_s: int | None = None
    resolve_p50_s: int | None = None
    resolve_p90_s: int | None = None
    people_peak_by_camera: dict[str, int] = Field(default_factory=dict)
    groups_total: int = 0
    groups_multi_camera: int = 0


def bounds(date_from: date, date_to: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """[start, end) in UTC for whole site-time days."""
    start = datetime.combine(date_from, time.min, tzinfo=tz)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz)
    return start, end


async def collect(
    sessions: async_sessionmaker[AsyncSession], date_from: date, date_to: date, tz: ZoneInfo
) -> DailyFacts:
    t0, t1 = bounds(date_from, date_to, tz)
    p = {"t0": t0, "t1": t1, "tz": str(tz)}
    facts = DailyFacts(date_from=date_from, date_to=date_to, timezone=str(tz))
    async with sessions() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT event_type, camera_id, severity, "
                    "extract(hour from start_ts AT TIME ZONE CAST(:tz AS text))::int, count(*) "
                    "FROM events.events WHERE status <> 'rejected' "
                    "AND start_ts >= :t0 AND start_ts < :t1 GROUP BY 1, 2, 3, 4"
                ),
                p,
            )
        ).all()
        by_type, by_cam, by_sev, by_hour = Counter(), Counter(), Counter(), Counter()
        for etype, cam, sev, hour, n in rows:
            by_type[etype] += n
            by_cam[cam] += n
            by_sev[sev] += n
            by_hour[f"{hour:02d}"] += n
        facts.events_total = sum(by_type.values())
        facts.by_type = dict(by_type.most_common())
        facts.by_camera = dict(by_cam.most_common())
        facts.by_severity = dict(
            sorted(by_sev.items(), key=lambda kv: -SEVERITY_RANK.get(kv[0], 0))
        )
        facts.by_hour = dict(sorted(by_hour.items()))

        facts.events_rejected = (
            await s.execute(
                text(
                    "SELECT count(*) FROM events.events WHERE status = 'rejected' "
                    "AND start_ts >= :t0 AND start_ts < :t1"
                ),
                p,
            )
        ).scalar_one()

        inc = (
            await s.execute(
                text(
                    "SELECT id::text, title, severity, event_type, camera_ids, "
                    "window_start AT TIME ZONE CAST(:tz AS text) FROM reasoning.incidents "
                    "WHERE status IN ('generated', 'reviewed', 'closed') "
                    "AND window_start >= :t0 AND window_start < :t1 "
                    "ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
                    "WHEN 'medium' THEN 2 ELSE 3 END, window_start LIMIT 8"
                ),
                p,
            )
        ).all()
        facts.incidents = [
            IncidentLine(
                id=r[0], title=r[1], severity=r[2], event_type=r[3], cameras=list(r[4]),
                at=r[5].strftime("%H:%M"),
            )
            for r in inc
        ]  # fmt: skip
        facts.incidents_total = (
            await s.execute(
                text(
                    "SELECT count(*) FROM reasoning.incidents WHERE status IN "
                    "('generated', 'reviewed', 'closed') AND window_start >= :t0 "
                    "AND window_start < :t1"
                ),
                p,
            )
        ).scalar_one()

        al = (
            await s.execute(
                text(
                    "SELECT count(*), count(*) FILTER (WHERE status = 'open'), "
                    "percentile_cont(0.5) WITHIN GROUP (ORDER BY "
                    "extract(epoch from acknowledged_at - created_at)), "
                    "percentile_cont(0.9) WITHIN GROUP (ORDER BY "
                    "extract(epoch from acknowledged_at - created_at)), "
                    "percentile_cont(0.5) WITHIN GROUP (ORDER BY "
                    "extract(epoch from resolved_at - created_at)), "
                    "percentile_cont(0.9) WITHIN GROUP (ORDER BY "
                    "extract(epoch from resolved_at - created_at)) "
                    "FROM core.alerts WHERE created_at >= :t0 AND created_at < :t1"
                ),
                p,
            )
        ).one()
        facts.alerts_total, facts.alerts_open = al[0], al[1]
        facts.ack_p50_s, facts.ack_p90_s, facts.resolve_p50_s, facts.resolve_p90_s = (
            None if v is None else round(v) for v in al[2:]
        )

        facts.people_peak_by_camera = {
            r[0]: int(r[1])
            for r in (
                await s.execute(
                    text(
                        "SELECT camera_id, max(c) FROM (SELECT camera_id, minute_ts, "
                        "sum(count) AS c FROM vision.minute_counts WHERE category = 'person' "
                        "AND minute_ts >= :t0 AND minute_ts < :t1 GROUP BY 1, 2) t "
                        "GROUP BY camera_id ORDER BY 2 DESC"
                    ),
                    p,
                )
            ).all()
        }
        g = (
            await s.execute(
                text(
                    "SELECT count(*), count(*) FILTER (WHERE cardinality(camera_ids) > 1) "
                    "FROM events.correlation_groups WHERE status <> 'merged' "
                    "AND start_ts >= :t0 AND start_ts < :t1"
                ),
                p,
            )
        ).one()
        facts.groups_total, facts.groups_multi_camera = g
    return facts


# --- narrative helpers (pure) ----------------------------------------------------------------

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def period_label(f: DailyFacts) -> str:
    if f.date_from == f.date_to:
        return f"{f.date_from:%A %d %B %Y}"
    return f"{f.date_from:%d %B %Y} to {f.date_to:%d %B %Y}"


def _walk(value: Any):
    if isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _walk(v)
    elif isinstance(value, list | tuple):
        for v in value:
            yield from _walk(v)
    elif value is not None:
        yield str(value)


def allowed_numbers(f: DailyFacts) -> set[str]:
    """Every number the figures contain, plus the digits of the period itself."""
    nums: set[str] = set()
    for token in _walk(f.model_dump(mode="json")):
        for m in _NUMBER.findall(token):
            nums.add(m)
            nums.add(m.lstrip("0") or "0")
    for m in _NUMBER.findall(period_label(f)):
        nums.add(m)
    # words like "one", "two" are not numbers here; 0 and 1 are harmless
    nums.update({"0", "1"})
    return nums


_CLOCK = re.compile(r"\b(\d{1,2}):(\d{2})\b")


def unsupported_numbers(narrative: str, f: DailyFacts) -> list[str]:
    """Numbers in the narrative that the figures do not contain. A clock time is one number: the
    figures only know whole hours (the busiest-hour buckets), so `12:00` passes when 12 is a bucket
    and `12:37` never does."""
    allowed = allowed_numbers(f)
    bad: set[str] = set()
    for m in _CLOCK.finditer(narrative):
        hour, minute = m.group(1), m.group(2)
        if minute != "00" or (hour not in allowed and hour.lstrip("0") not in allowed):
            bad.add(m.group(0))
    rest = _CLOCK.sub(" ", narrative)
    bad.update(
        m for m in _NUMBER.findall(rest) if m not in allowed and m.lstrip("0") not in allowed
    )
    return sorted(bad)


def figures_text(f: DailyFacts) -> str:
    """The figures as plain lines for the narrative prompt: readable labels, no field names for
    a small model to echo back."""

    def pairs(record: dict[str, int], label=lambda k: k) -> str:
        return ", ".join(f"{label(k)} {v}" for k, v in record.items()) or "none"

    lines = [
        f"Verified events: {f.events_total}",
        f"Candidates rejected by the vision model as false alarms: {f.events_rejected}",
        f"Incident reports written: {f.incidents_total}",
        f"Events by type: {pairs(f.by_type, lambda k: k.replace('_', ' '))}",
        f"Events by camera: {pairs(f.by_camera)}",
        f"Events by severity: {pairs(f.by_severity)}",
    ]
    busiest = sorted(f.by_hour.items(), key=lambda kv: -kv[1])[:3]
    lines.append(
        "Busiest hours (site time, hour starting): "
        + (", ".join(f"{h}:00 with {n} events" for h, n in busiest) or "none")
    )
    lines.append(f"Alerts raised: {f.alerts_total}, still open: {f.alerts_open}")
    if f.ack_p50_s is not None:
        lines.append(
            f"Alerts acknowledged: median {f.ack_p50_s} seconds, "
            f"90th percentile {f.ack_p90_s} seconds"
        )
    if f.resolve_p50_s is not None:
        lines.append(
            f"Alerts resolved: median {f.resolve_p50_s} seconds, "
            f"90th percentile {f.resolve_p90_s} seconds"
        )
    if f.people_peak_by_camera:
        lines.append(
            "Most people seen at once in a minute: "
            + ", ".join(f"{c} {n}" for c, n in f.people_peak_by_camera.items())
        )
    lines.append(
        f"Event groups linked across cameras: {f.groups_multi_camera} of {f.groups_total} groups"
    )
    return "\n".join(lines)


def clock_hour(h: str) -> str:
    return f"{h}:00"


def template_narrative(f: DailyFacts) -> str:
    """The report's text when no model could be trusted: only the figures, in sentences."""
    span = f"On {period_label(f)}" if f.date_from == f.date_to else f"From {period_label(f)}"
    parts = [
        f"{span}, {f.events_total} verified event"
        f"{'' if f.events_total == 1 else 's'} and {f.incidents_total} incident report"
        f"{'' if f.incidents_total == 1 else 's'} were recorded."
    ]
    if f.events_total:
        top_type = next(iter(f.by_type))
        top_cam = next(iter(f.by_camera))
        parts.append(
            f"The most common event type was {top_type.replace('_', ' ')} "
            f"({f.by_type[top_type]}), and camera {top_cam} raised the most events "
            f"({f.by_camera[top_cam]})."
        )
        if f.by_hour:
            hour = max(f.by_hour, key=lambda h: f.by_hour[h])
            parts.append(
                f"The busiest hour began at {clock_hour(hour)} with {f.by_hour[hour]} events."
            )
        high = {k: v for k, v in f.by_severity.items() if SEVERITY_RANK.get(k, 0) >= 2}
        if high:
            parts.append(
                "High-severity or above: " + ", ".join(f"{v} {k}" for k, v in high.items()) + "."
            )
    if f.events_rejected:
        parts.append(
            f"The vision model rejected {f.events_rejected} further candidate"
            f"{'' if f.events_rejected == 1 else 's'} as false alarms."
        )
    if f.ack_p50_s is not None:
        parts.append(
            f"Alerts were acknowledged after a median of {f.ack_p50_s} seconds "
            f"(90th percentile {f.ack_p90_s})."
        )
    if f.alerts_open:
        parts.append(f"{f.alerts_open} alert{'' if f.alerts_open == 1 else 's'} remained open.")
    if not f.events_total and not f.incidents_total:
        parts.append("Nothing was recorded in this period.")
    return " ".join(parts)
