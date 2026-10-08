"""The assistant's tools (design §10.3). Each is a function of validated arguments that returns
text for the model (with citation tags) — never raw rows — and registers what it found in the
turn's `Evidence`.

All SQL here is written out and parameterised; nothing is generated from the model's text
(CLAUDE.md "No generated SQL"). Times arrive either as ISO instants or, preferably, as a phrase
(`when`) the same resolver as search understands, because a small model computes dates badly."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, Field, TypeAdapter, ValidationError, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vms_common.contracts.search import SearchFilters, SearchRequest

from retrieval.assistant.evidence import Evidence
from retrieval.domain.plan import resolve_time
from retrieval.pipeline import SearchPipeline

CATEGORIES = (
    "person",
    "backpack",
    "handbag",
    "suitcase",
    "car",
    "bicycle",
    "motorcycle",
    "bus",
    "truck",
)
SEVERITIES = ("low", "medium", "high", "critical")
MAX_ROWS = 10


def _noun(category: str, n: int) -> str:
    if category == "person":
        return "person" if n == 1 else "people"
    return category if n == 1 else f"{category}s"


def tally(severities: list[str]) -> str:
    """`severity: 5 HIGH, 1 MEDIUM` — the count and the worst case at a glance, in the words the
    answer is expected to use (a small model does not connect "serious" to a line saying HIGH)."""
    order = ("critical", "high", "medium", "low")
    counts = {sev: severities.count(sev) for sev in order if sev in severities}
    return "severity: " + (", ".join(f"{n} {sev.upper()}" for sev, n in counts.items()) or "none")


@dataclass
class ToolContext:
    sessions: async_sessionmaker[AsyncSession]
    pipeline: SearchPipeline
    tz: ZoneInfo
    evidence: Evidence
    archive_since: datetime | None = None

    def now(self) -> datetime:
        return datetime.now(UTC)

    def window(
        self, when: str | None, start: datetime | None, end: datetime | None
    ) -> tuple[datetime | None, datetime | None]:
        if when:
            got = resolve_time(when, self.now(), self.tz)
            if got:
                start, end = got
        if self.archive_since and (start is None or start < self.archive_since):
            start = self.archive_since
        return start, end

    def clock(self, ts: datetime) -> str:
        return ts.astimezone(self.tz).strftime("%d %b %H:%M:%S")


_AWARE = TypeAdapter(AwareDatetime)


class _Timed(BaseModel):
    when: str | None = Field(
        default=None,
        description='a phrase: "today", "yesterday", "last hour", "last 30 minutes", "this morning"',  # noqa: E501
    )
    # Not shown to the model (see `tool_catalogue`): a 3B model fills these with "13:19" next to a
    # perfectly good `when`. Anything that is not a full ISO instant is ignored rather than fatal.
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None

    @field_validator("start", "end", mode="before")
    @classmethod
    def _ignore_unparseable_times(cls, v: object) -> object:
        try:
            return _AWARE.validate_python(v) if v is not None else None
        except ValidationError:
            return None


class SearchFootage(_Timed):
    query: str = Field(min_length=2, description="what to look for, in plain words")
    cameras: list[str] = Field(default_factory=list)
    mode: str = Field(default="fast", description='"fast" or "reason"')

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        return v if v in ("fast", "reason") else "fast"


class ListEvents(_Timed):
    type: str | None = Field(
        default=None, description="intrusion, loitering, crowding, running, abandoned_object"
    )
    camera: str | None = None
    severity: str | None = None
    limit: int = Field(default=MAX_ROWS, ge=1, le=20)

    @field_validator("severity")
    @classmethod
    def _sev(cls, v: str | None) -> str | None:
        return v if v in SEVERITIES else None


class ListIncidents(_Timed):
    severity: str | None = None
    camera: str | None = None
    limit: int = Field(default=5, ge=1, le=10)

    @field_validator("severity")
    @classmethod
    def _sev(cls, v: str | None) -> str | None:
        return v if v in SEVERITIES else None


class GetIncident(BaseModel):
    id: str = Field(
        min_length=4, description="incident id or the 8-character tag from [I:xxxxxxxx]"
    )


class GetTimeline(_Timed):
    cameras: list[str] = Field(default_factory=list)


class CountObjects(_Timed):
    category: str = Field(
        description="person, backpack, handbag, suitcase, car, bicycle, motorcycle, bus, truck"
    )
    camera: str | None = None
    group_by: str = Field(default="none", description='"none", "camera" or "hour"')

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str) -> str:
        v = v.lower().strip()
        if v in ("people", "persons", "pedestrian", "pedestrians"):
            v = "person"
        if v not in CATEGORIES:
            raise ValueError(f"category must be one of {', '.join(CATEGORIES)}")
        return v

    @field_validator("group_by")
    @classmethod
    def _gb(cls, v: str) -> str:
        return v if v in ("none", "camera", "hour") else "none"


class GetDailyReport(BaseModel):
    date: str = Field(description="YYYY-MM-DD, or 'today' / 'yesterday'")


# --- implementations ---------------------------------------------------------------------


async def search_footage(ctx: ToolContext, a: SearchFootage) -> str:
    start, end = ctx.window(a.when, a.start, a.end)
    resp = await ctx.pipeline.text(
        SearchRequest(
            query=a.query,
            mode=a.mode,  # type: ignore[arg-type]
            filters=SearchFilters(cameras=a.cameras, start=start, end=end),
            top_k=5,
        )
    )
    if not resp.results:
        return "No footage matched."
    header = f"{len(resp.results)} matching moment(s), best first:"
    lines = []
    for r in resp.results:
        seg = r.segment_ids[0] if r.segment_ids else r.result_id
        tag = ctx.evidence.footage(
            seg,
            r.start_ts.isoformat(),
            f"{r.camera_id} {ctx.clock(r.start_ts)}",
            camera=r.camera_id,
        )
        bits = [
            f"{tag} {r.camera_id} at {ctx.clock(r.start_ts)}, match {round(r.score * 100)}%",
            ", ".join(r.categories + r.colors[:3] + r.zones) or "",
        ]
        if r.caption:
            bits.append(f'event: "{r.caption}"')
        if r.trace:
            bits.append(f"why: {r.trace}")
        lines.append("; ".join(b for b in bits if b))
    return header + "\n" + "\n".join(lines)


_EVENTS_SQL = text(
    "SELECT id::text, camera_id, event_type, severity, status, start_ts, "
    "verification->>'caption' AS caption FROM events.events "
    "WHERE status <> 'rejected' "
    "AND (CAST(:etype AS text) IS NULL OR event_type = CAST(:etype AS text)) "
    "AND (CAST(:cam AS text) IS NULL OR camera_id = CAST(:cam AS text)) "
    "AND (CAST(:sev AS text) IS NULL OR severity = CAST(:sev AS text)) "
    "AND (CAST(:t0 AS timestamptz) IS NULL OR end_ts >= CAST(:t0 AS timestamptz)) "
    "AND (CAST(:t1 AS timestamptz) IS NULL OR start_ts <= CAST(:t1 AS timestamptz)) "
    "ORDER BY start_ts DESC LIMIT :n"
)


async def list_events(ctx: ToolContext, a: ListEvents) -> str:
    start, end = ctx.window(a.when, a.start, a.end)
    async with ctx.sessions() as s:
        rows = (
            await s.execute(
                _EVENTS_SQL,
                {
                    "etype": a.type,
                    "cam": a.camera,
                    "sev": a.severity,
                    "t0": start,
                    "t1": end,
                    "n": a.limit,
                },
            )
        ).all()
    if not rows:
        return "No verified events in that period."
    lines = []
    for r in rows:
        tag = ctx.evidence.event(r[0], f"{r[2]} on {r[1]}", camera=r[1], ts=r[5].isoformat())
        cap = f' Description: "{r[6]}"' if r[6] else ""
        lines.append(
            f"{tag} event: {r[2].replace('_', ' ')}, severity {r[3].upper()}, camera {r[1]}, "
            f"{ctx.clock(r[5])}.{cap}"
        )
    return (
        f"{len(rows)} verified event(s) ({tally([r[3] for r in rows])}), newest first:\n"
        + "\n".join(lines)
    )


_INCIDENTS_SQL = text(
    "SELECT id::text, title, severity, event_type, status, window_start, camera_ids, "
    "report->>'summary' FROM reasoning.incidents WHERE status IN ('generated','reviewed','closed') "
    "AND (CAST(:sev AS text) IS NULL OR severity = CAST(:sev AS text)) "
    "AND (CAST(:cam AS text) IS NULL OR CAST(:cam AS text) = ANY(camera_ids)) "
    "AND (CAST(:t0 AS timestamptz) IS NULL OR window_end >= CAST(:t0 AS timestamptz)) "
    "AND (CAST(:t1 AS timestamptz) IS NULL OR window_start <= CAST(:t1 AS timestamptz)) "
    "ORDER BY window_start DESC LIMIT :n"
)


async def list_incidents(ctx: ToolContext, a: ListIncidents) -> str:
    start, end = ctx.window(a.when, a.start, a.end)
    async with ctx.sessions() as s:
        rows = (
            await s.execute(
                _INCIDENTS_SQL,
                {"sev": a.severity, "cam": a.camera, "t0": start, "t1": end, "n": a.limit},
            )
        ).all()
    if not rows:
        return "No incident reports in that period."
    lines = []
    for r in rows:
        tag = ctx.evidence.incident(r[0], r[1], ts=r[5].isoformat())
        lines.append(
            f'{tag} incident report "{r[1]}" — severity {r[2].upper()}, '
            f"type {r[3].replace('_', ' ')}, camera {', '.join(r[6])}, {ctx.clock(r[5])}. "
            f"Summary: {(r[7] or '')[:200]}"
        )
    return (
        f"{len(rows)} incident report(s) ({tally([r[2] for r in rows])}), newest first:\n"
        + "\n".join(lines)
    )


async def get_incident(ctx: ToolContext, a: GetIncident) -> str:
    key = a.id.strip().strip("[]")
    if key[:2] in ("I:",):
        key = key[2:]
    async with ctx.sessions() as s:
        row = (
            await s.execute(
                text(
                    "SELECT id::text, title, severity, event_type, status, window_start, camera_ids, "  # noqa: E501
                    "report FROM reasoning.incidents WHERE id::text LIKE :k || '%' "
                    "AND status IN ('generated','reviewed','closed') ORDER BY created_at DESC LIMIT 1"  # noqa: E501
                ),
                {"k": key},
            )
        ).first()
    if row is None:
        return "No incident with that id."
    report = row[7] or {}
    tag = ctx.evidence.incident(row[0], row[1], ts=row[5].isoformat())
    out = [
        f'{tag} incident report "{row[1]}" — severity {row[2].upper()}, '
        f"type {row[3].replace('_', ' ')}, camera {', '.join(row[6])}, {ctx.clock(row[5])}, "
        f"status {row[4]}, confidence {report.get('confidence')}",
        f"summary: {report.get('summary', '')}",
    ]
    for step in report.get("causal_chain", [])[:4]:
        out.append(f"step {step['step']}: {step['description']}")
    for act in report.get("recommended_actions", [])[:3]:
        out.append(f"recommended: {act['action']} ({act['priority']})")
    for lim in report.get("limitations", [])[:2]:
        out.append(f"limitation: {lim}")
    return "\n".join(out)


async def get_timeline(ctx: ToolContext, a: GetTimeline) -> str:
    start, end = ctx.window(a.when, a.start, a.end)
    cams = a.cameras or None
    async with ctx.sessions() as s:
        ev = (
            await s.execute(
                text(
                    "SELECT id::text, camera_id, event_type, severity, start_ts, "
                    "verification->>'caption' FROM events.events WHERE status <> 'rejected' "
                    "AND (CAST(:cams AS text[]) IS NULL OR camera_id = ANY(CAST(:cams AS text[]))) "
                    "AND (CAST(:t0 AS timestamptz) IS NULL OR end_ts >= CAST(:t0 AS timestamptz)) "
                    "AND (CAST(:t1 AS timestamptz) IS NULL OR start_ts <= CAST(:t1 AS timestamptz)) "  # noqa: E501
                    "ORDER BY start_ts DESC LIMIT 15"
                ),
                {"cams": cams, "t0": start, "t1": end},
            )
        ).all()
        inc = (
            await s.execute(
                text(
                    "SELECT id::text, title, severity, window_start FROM reasoning.incidents "
                    "WHERE status IN ('generated','reviewed','closed') "
                    "AND (CAST(:cams AS text[]) IS NULL OR camera_ids && CAST(:cams AS text[])) "
                    "AND (CAST(:t0 AS timestamptz) IS NULL OR window_end >= CAST(:t0 AS timestamptz)) "  # noqa: E501
                    "AND (CAST(:t1 AS timestamptz) IS NULL OR window_start <= CAST(:t1 AS timestamptz)) "  # noqa: E501
                    "ORDER BY window_start DESC LIMIT 8"
                ),
                {"cams": cams, "t0": start, "t1": end},
            )
        ).all()
    items: list[tuple[datetime, str]] = []
    for r in ev:
        tag = ctx.evidence.event(r[0], f"{r[2]} on {r[1]}", camera=r[1], ts=r[4].isoformat())
        items.append(
            (
                r[4],
                f"{ctx.clock(r[4])} {tag} event: {r[2].replace('_', ' ')}, severity "
                f"{r[3].upper()}, camera {r[1]}." + (f' Description: "{r[5]}"' if r[5] else ""),
            )
        )
    for r in inc:
        tag = ctx.evidence.incident(r[0], r[1], ts=r[3].isoformat())
        items.append(
            (r[3], f'{ctx.clock(r[3])} {tag} incident report "{r[1]}" — severity {r[2].upper()}')
        )
    if not items:
        return "Nothing happened in that period (no verified events or incident reports)."
    items.sort(key=lambda x: x[0])
    return "Timeline, oldest first:\n" + "\n".join(line for _t, line in items[-20:])


# Three fixed statements, one per grouping. `sum(count)` per minute is the number of tracked
# objects of that category seen in that minute across the chosen cameras.
_COUNT_NONE = text(
    "SELECT COALESCE(max(c), 0), COALESCE(round(avg(c)::numeric, 1), 0), count(*) FROM ("
    "SELECT minute_ts, sum(count) AS c FROM vision.minute_counts WHERE category = :cat "
    "AND (CAST(:cam AS text) IS NULL OR camera_id = CAST(:cam AS text)) "
    "AND (CAST(:t0 AS timestamptz) IS NULL OR minute_ts >= CAST(:t0 AS timestamptz)) "
    "AND (CAST(:t1 AS timestamptz) IS NULL OR minute_ts < CAST(:t1 AS timestamptz)) "
    "GROUP BY minute_ts) t"
)
_COUNT_CAMERA = text(
    "SELECT camera_id, max(count), round(avg(count)::numeric, 1), count(*) FROM vision.minute_counts "  # noqa: E501
    "WHERE category = :cat "
    "AND (CAST(:cam AS text) IS NULL OR camera_id = CAST(:cam AS text)) "
    "AND (CAST(:t0 AS timestamptz) IS NULL OR minute_ts >= CAST(:t0 AS timestamptz)) "
    "AND (CAST(:t1 AS timestamptz) IS NULL OR minute_ts < CAST(:t1 AS timestamptz)) "
    "GROUP BY camera_id ORDER BY camera_id"
)
_COUNT_HOUR = text(
    "SELECT date_trunc('hour', minute_ts AT TIME ZONE 'Asia/Kolkata') AS h, max(c), "
    "round(avg(c)::numeric, 1) FROM (SELECT minute_ts, sum(count) AS c FROM vision.minute_counts "
    "WHERE category = :cat "
    "AND (CAST(:cam AS text) IS NULL OR camera_id = CAST(:cam AS text)) "
    "AND (CAST(:t0 AS timestamptz) IS NULL OR minute_ts >= CAST(:t0 AS timestamptz)) "
    "AND (CAST(:t1 AS timestamptz) IS NULL OR minute_ts < CAST(:t1 AS timestamptz)) "
    "GROUP BY minute_ts) t GROUP BY h ORDER BY h LIMIT 48"
)


async def count_objects(ctx: ToolContext, a: CountObjects) -> str:
    start, end = ctx.window(a.when, a.start, a.end)
    p = {"cat": a.category, "cam": a.camera, "t0": start, "t1": end}
    async with ctx.sessions() as s:
        if a.group_by == "camera":
            rows = (await s.execute(_COUNT_CAMERA, p)).all()
            if not rows:
                return f"No {a.category} counts recorded in that period."
            return "\n".join(
                f"{r[0]}: peak {r[1]} per minute, average {r[2]}, over {r[3]} recorded minutes"
                for r in rows
            )
        if a.group_by == "hour":
            rows = (await s.execute(_COUNT_HOUR, p)).all()
            if not rows:
                return f"No {a.category} counts recorded in that period."
            best = max(rows, key=lambda r: r[1])
            head = (
                f"Busiest hour: {best[0]:%d %b %H:00} IST, with up to {best[1]} "
                f"{_noun(a.category, best[1])} seen at once (average {best[2]} per minute)."
            )
            return (
                head
                + "\nAll hours (IST), peak / average per minute:\n"
                + "\n".join(f"{r[0]:%d %b %H:00}: peak {r[1]}, average {r[2]}" for r in rows)
            )
        row = (await s.execute(_COUNT_NONE, p)).first()
    if row is None or not row[2]:
        return f"No {a.category} counts recorded in that period."
    return (
        f"Most {_noun(a.category, 2)} seen at once in a minute: {row[0]} (average {row[1]} per minute, "  # noqa: E501
        f"over {row[2]} recorded minutes)."
    )


async def get_daily_report(ctx: ToolContext, a: GetDailyReport) -> str:
    when = a.date.strip().lower()
    today = datetime.now(ctx.tz).date()
    if when == "today":
        day = today
    elif when == "yesterday":
        day = today.fromordinal(today.toordinal() - 1)
    else:
        try:
            day = datetime.strptime(when, "%Y-%m-%d").date()  # noqa: DTZ007 - a calendar date
        except ValueError:
            return "Give the date as YYYY-MM-DD, today or yesterday."
    async with ctx.sessions() as s:
        row = (
            await s.execute(
                text(
                    "SELECT narrative, facts FROM reasoning.daily_reports "
                    "WHERE status = 'ready' AND date_from <= :d AND date_to >= :d "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"d": day},
            )
        ).first()
    if row is None:
        return f"No daily report exists for {day}."
    return f"Daily report for {day}:\n{(row[0] or '')[:1500]}\nfacts: {json.dumps(row[1])[:800]}"


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    run: Callable[[ToolContext, Any], Awaitable[str]]


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool(
            "search_footage",
            "Find moments in the recorded video from a description (people, clothing, objects, places).",  # noqa: E501
            SearchFootage,
            search_footage,
        ),
        Tool(
            "list_events",
            "List verified events (intrusion, loitering, crowding, running, abandoned_object) with filters.",  # noqa: E501
            ListEvents,
            list_events,
        ),
        Tool(
            "list_incidents",
            "List written incident reports in a period.",
            ListIncidents,
            list_incidents,
        ),
        Tool(
            "get_incident",
            "Read one incident report: summary, how it unfolded, recommended actions.",
            GetIncident,
            get_incident,
        ),
        Tool(
            "get_timeline",
            "Everything that happened (events and incident reports) in a period, in order.",
            GetTimeline,
            get_timeline,
        ),
        Tool(
            "count_objects",
            "How many people/objects were seen: peak and average per minute, optionally per camera or per hour.",  # noqa: E501
            CountObjects,
            count_objects,
        ),
        Tool(
            "get_daily_report",
            "Read the daily security report for a date.",
            GetDailyReport,
            get_daily_report,
        ),
    )
}


def tool_catalogue() -> str:
    """The tools as the prompt shows them: name, purpose and the arguments with their types."""
    lines = []
    for t in TOOLS.values():
        props = {
            k: v
            for k, v in t.args.model_json_schema().get("properties", {}).items()
            if k not in ("start", "end")
        }
        args = ", ".join(
            f"{k}: {v.get('type', 'any')}"
            + (f" ({v['description']})" if v.get("description") else "")
            for k, v in props.items()
        )
        lines.append(f"- {t.name}({args})\n    {t.description}")
    return "\n".join(lines)
