"""PDF reports (P6-J1, P6-J2; docs/style_guide.md §B.11): Jinja2 → HTML → WeasyPrint.

`incident_html` / `daily_html` are pure (data in, HTML out) and are what the unit tests read.
`write_incident_pdf` / `write_daily_pdf` load a finished report, render it, store the PDF in the
reports bucket and note its address on the row; the worker calls them after a report is final and
treats a failure as "no PDF", never as a failed report.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, PackageLoader, select_autoescape
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vms_common.contracts.reasoning import IncidentReportV1
from vms_common.logging import get_logger

from reasoning.reports.facts import DailyFacts, period_label

log = get_logger(__name__)

PHASE_LABEL = {
    "baseline": "Baseline",
    "precursor": "Precursor",
    "escalation": "Escalation",
    "action": "Action",
    "aftermath": "Aftermath",
}
# Severity is a shape and a word, never a colour alone (§B.3).
SEVERITY_MARK = {"low": "○", "medium": "◇", "high": "▲", "critical": "■"}
MAX_EVIDENCE_FRAMES = 8
_ENV = Environment(
    loader=PackageLoader("reasoning.reports", "templates"),
    autoescape=select_autoescape(["html"]),
)


def _css_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def stylesheet(*, left: str, right: str, footer: str) -> str:
    return _ENV.get_template("base.css").render(
        header_left=_css_text(left), header_right=_css_text(right), footer=_css_text(footer)
    )


def _clock(ts: datetime, tz: ZoneInfo) -> str:
    return ts.astimezone(tz).strftime("%H:%M:%S")


def window_text(start: datetime, end: datetime, tz: ZoneInfo) -> str:
    s, e = start.astimezone(tz), end.astimezone(tz)
    return f"{s:%d %b %Y}, {s:%H:%M:%S} to {e:%H:%M:%S} {tz.key if hasattr(tz, 'key') else tz}"


def provenance_note(provenance: dict[str, Any]) -> str:
    """The same sentence the report page shows under the report."""
    bits = []
    if provenance.get("synthesis_model"):
        bits.append(f"Report by {provenance['synthesis_model']}")
    if provenance.get("tg"):
        bits.append(
            "phases from detector timing (the model could not place them)"
            if provenance.get("fallback_used")
            else f"phases by {provenance['tg']}"
        )
    if provenance.get("profile"):
        bits.append(f"{provenance['profile']} profile")
    return " · ".join(bits) or "Provenance not recorded"


def _data_uri(data: bytes, max_edge: int = 720) -> str:
    """A JPEG as a data URI, shrunk to what a column of a printed page can show."""
    from PIL import Image  # noqa: PLC0415

    try:
        with Image.open(io.BytesIO(data)) as image:
            if max(image.size) > max_edge:
                image = image.convert("RGB")
                image.thumbnail((max_edge, max_edge))
                out = io.BytesIO()
                image.save(out, format="JPEG", quality=82)
                data = out.getvalue()
    except OSError:
        pass  # not decodable here: embed it as it is and let the renderer decide
    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")


def frame_uris(evidence: dict[str, Any] | None, limit: int = MAX_EVIDENCE_FRAMES) -> list[str]:
    """The evidence frames worth printing: the first of each stage and view, then the rest in
    order, at most `limit`."""
    firsts: list[str] = []
    rest: list[str] = []
    for phase in (evidence or {}).get("phases", []):
        for view in phase.get("views", []):
            for n, frame in enumerate(view.get("frames", [])):
                (firsts if n == 0 else rest).append(frame["uri"])
    return (firsts + rest)[:limit]


def incident_html(
    incident: dict[str, Any],
    images: dict[str, bytes],
    *,
    tz: ZoneInfo,
    generated_at: datetime,
    site: str,
) -> str:
    """`incident`: a `reasoning.incidents` row as a dict; `images`: frame uri -> JPEG bytes."""
    report = IncidentReportV1.model_validate(incident["report"])
    evidence = incident.get("evidence") or {}
    timeline = {p["phase"]: p for p in evidence.get("phase_timeline", [])}
    phases = []
    for p in report.phase_analysis:
        span = timeline.get(p.phase)
        when = (
            f"{_clock(datetime.fromisoformat(span['start']), tz)} to "
            f"{_clock(datetime.fromisoformat(span['end']), tz)}"
            if span
            else ""
        )
        phases.append(
            {
                "label": PHASE_LABEL.get(p.phase, p.phase),
                "when": when,
                "summary": p.summary,
                "evidence": p.evidence,
            }
        )
    frames = []
    wanted = set(frame_uris(evidence))
    for phase in evidence.get("phases", []):
        for view in phase.get("views", []):
            for frame in view.get("frames", []):
                if frame["uri"] in wanted and frame["uri"] in images:
                    ts = datetime.fromisoformat(frame["ts"].replace("Z", "+00:00"))
                    frames.append(
                        {
                            "src": _data_uri(images[frame["uri"]]),
                            "caption": (
                                f"{PHASE_LABEL.get(phase['phase'], phase['phase'])} · "
                                f"{view['camera_id']} · {_clock(ts, tz)} · {frame['id']}"
                            ),
                        }
                    )
    header = {
        "title": report.title or incident["title"],
        "severity": incident["severity"],
        "event_type_label": incident["event_type"].replace("_", " "),
        "window_text": window_text(incident["window_start"], incident["window_end"], tz),
        "cameras": incident["camera_ids"],
        "confidence": report.confidence,
        "notes": incident.get("notes"),
    }
    css = stylesheet(
        left=f"{site} · incident report",
        right=window_text(incident["window_start"], incident["window_end"], tz),
        footer=f"Generated by GenAI-VMS, {incident.get('provenance', {}).get('profile', 'unknown')}"
        f" profile, {generated_at.astimezone(tz):%Y-%m-%d %H:%M} {tz.key}",
    )
    return _ENV.get_template("incident.html").render(
        css=css,
        i=header,
        r=report,
        phases=phases,
        frames=frames,
        severity_mark=SEVERITY_MARK.get(incident["severity"], ""),
        provenance=provenance_note(incident.get("provenance") or {}),
    )


def _hours_svg(by_hour: dict[str, int]) -> str:
    """24 columns, drawn with presentation attributes: WeasyPrint's SVG does not read the page's
    CSS classes or custom properties."""
    counts = [by_hour.get(f"{h:02d}", 0) for h in range(24)]
    top = max(max(counts), 1)
    parts = []
    for h, n in enumerate(counts):
        height = 64 * n / top
        x = h * 20 + 4
        parts.append(
            f'<rect x="{x}" y="{74 - height:.1f}" width="14" height="{height:.1f}" '
            f'fill="#146c8a"><title>{h:02d}:00, {n} events</title></rect>'
        )
        if n:
            parts.append(
                f'<text x="{x + 7}" y="{70 - height:.1f}" text-anchor="middle" font-size="8" '
                f'font-family="DejaVu Sans, sans-serif" fill="#1b2330">{n}</text>'
            )
        if h % 3 == 0:
            parts.append(
                f'<text x="{x + 7}" y="88" text-anchor="middle" font-size="8" '
                f'font-family="DejaVu Sans, sans-serif" fill="#5b6472">{h:02d}</text>'
            )
    parts.append('<line x1="0" y1="74.5" x2="484" y2="74.5" stroke="#cfd6df" stroke-width="0.6"/>')
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 484 94" width="100%" '
        'role="img" aria-label="Events by hour of day">' + "".join(parts) + "</svg>"
    )


def _span(seconds: int | None) -> str:
    if seconds is None:
        return "no data"
    minutes, secs = divmod(seconds, 60)
    return f"{minutes} min {secs:02d} s" if minutes else f"{secs} s"


def daily_html(
    report: dict[str, Any], *, tz: ZoneInfo, generated_at: datetime, site: str, profile: str
) -> str:
    """`report`: a `reasoning.daily_reports` row as a dict (facts, narrative, narrative_source)."""
    f = DailyFacts.model_validate(report["facts"])
    period = period_label(f)
    css = stylesheet(
        left=f"{site} · daily security report",
        right=period,
        footer=f"Generated by GenAI-VMS, {profile} profile, "
        f"{generated_at.astimezone(tz):%Y-%m-%d %H:%M} {tz.key}",
    )
    ranked = lambda d: sorted(d.items(), key=lambda kv: -kv[1])  # noqa: E731
    return _ENV.get_template("daily.html").render(
        css=css,
        f=f,
        period=period,
        narrative=report["narrative"] or "",
        narrative_source=report.get("narrative_source"),
        high=f.by_severity.get("high", 0) + f.by_severity.get("critical", 0),
        hours_svg=_hours_svg(f.by_hour),
        by_type=[(k.replace("_", " "), v) for k, v in ranked(f.by_type)],
        by_camera=ranked(f.by_camera),
        by_severity=ranked(f.by_severity),
        ack_p50=_span(f.ack_p50_s),
        ack_p90=_span(f.ack_p90_s),
        resolve_p50=_span(f.resolve_p50_s),
        resolve_p90=_span(f.resolve_p90_s),
        peaks=ranked(f.people_peak_by_camera),
    )


def html_to_pdf(html: str) -> bytes:
    from weasyprint import HTML  # noqa: PLC0415 - heavy, and needs system libraries

    return HTML(string=html).write_pdf()


# ---- storing -------------------------------------------------------------------------------


async def _rows(
    sessions: async_sessionmaker[AsyncSession], sql: str, **params: Any
) -> dict[str, Any] | None:
    async with sessions() as s:
        row = (await s.execute(text(sql), params)).mappings().first()
    return dict(row) if row else None


async def write_incident_pdf(
    *,
    sessions: async_sessionmaker[AsyncSession],
    images,  # anything with `async image(uri) -> bytes`
    store,  # anything with `async put(uri, data, content_type)`
    incident_id: uuid.UUID,
    bucket: str,
    tz: ZoneInfo,
    site: str,
) -> str | None:
    row = await _rows(
        sessions,
        "SELECT title, severity, event_type, camera_ids, window_start, window_end, report, "
        "evidence, provenance, notes FROM reasoning.incidents WHERE id = :i AND report IS NOT NULL",
        i=incident_id,
    )
    if row is None:
        return None
    frames: dict[str, bytes] = {}
    for uri in frame_uris(row["evidence"]):
        try:
            frames[uri] = await images.image(uri)
        except Exception as exc:  # a frame that is gone is a gap in the picture grid, not a failure
            log.warning("pdf_frame_missing", uri=uri, error=type(exc).__name__)
    html = incident_html(row, frames, tz=tz, generated_at=datetime.now(UTC), site=site)
    pdf = await asyncio.to_thread(html_to_pdf, html)
    uri = f"s3://{bucket}/incidents/{incident_id}.pdf"
    await store.put(uri, pdf, "application/pdf")
    async with sessions() as s, s.begin():
        await s.execute(
            text("UPDATE reasoning.incidents SET pdf_uri = :u WHERE id = :i"),
            {"u": uri, "i": incident_id},
        )
    return uri


async def write_daily_pdf(
    *,
    sessions: async_sessionmaker[AsyncSession],
    store,
    report_id: uuid.UUID,
    bucket: str,
    tz: ZoneInfo,
    site: str,
    profile: str,
) -> str | None:
    row = await _rows(
        sessions,
        "SELECT facts, narrative, narrative_source FROM reasoning.daily_reports "
        "WHERE id = :i AND status = 'ready'",
        i=report_id,
    )
    if row is None or row["facts"] is None:
        return None
    facts = row["facts"] if isinstance(row["facts"], dict) else json.loads(row["facts"])
    html = daily_html(
        {**row, "facts": facts}, tz=tz, generated_at=datetime.now(UTC), site=site, profile=profile
    )
    pdf = await asyncio.to_thread(html_to_pdf, html)
    uri = f"s3://{bucket}/daily/{report_id}.pdf"
    await store.put(uri, pdf, "application/pdf")
    async with sessions() as s, s.begin():
        await s.execute(
            text("UPDATE reasoning.daily_reports SET pdf_uri = :u WHERE id = :i"),
            {"u": uri, "i": report_id},
        )
    return uri


def daily_period(date_from: date, date_to: date) -> str:
    """Kept for callers that only have the dates (the file name a person is offered)."""
    return (
        f"{date_from:%Y-%m-%d}"
        if date_from == date_to
        else f"{date_from:%Y-%m-%d}_{date_to:%Y-%m-%d}"
    )


__all__: Iterable[str] = [
    "incident_html",
    "daily_html",
    "html_to_pdf",
    "write_incident_pdf",
    "write_daily_pdf",
]
