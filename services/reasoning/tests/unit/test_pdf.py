"""PDF reports (P6-J1, P6-J2): what the HTML says, that it becomes a PDF, and that a PDF that
cannot be made never fails a report. The incidents are five stored ones (the synthesis fixtures)."""

from __future__ import annotations

import base64
import io
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from markupsafe import escape
from PIL import Image
from reasoning import worker as worker_module
from reasoning.reports.pdf import (
    MAX_EVIDENCE_FRAMES,
    daily_html,
    frame_uris,
    html_to_pdf,
    incident_html,
    provenance_note,
    stylesheet,
)
from reasoning.worker import ReasoningWorker

FIXTURES = sorted((Path(__file__).resolve().parents[1] / "fixtures").glob("incident_*.json"))
TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)


def jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (90, 120, 150)).save(buffer, format="JPEG")
    return buffer.getvalue()


def incident_row(path: Path, **over) -> tuple[dict, dict[str, bytes]]:
    fx = json.loads(path.read_text())
    report, evidence = fx["report"], fx["evidence"]
    row = {
        "title": report["title"],
        "severity": fx["severity"],
        "event_type": fx["event_type"],
        "camera_ids": report["cameras"],
        "window_start": datetime.fromisoformat(evidence["window"]["start"].replace("Z", "+00:00")),
        "window_end": datetime.fromisoformat(evidence["window"]["end"].replace("Z", "+00:00")),
        "report": report,
        "evidence": evidence,
        "provenance": {**report.get("provenance", {}), "profile": "local"},
        "notes": None,
    } | over
    images = {uri: jpeg() for uri in frame_uris(evidence, 99)}
    return row, images


def render(path: Path, **over) -> str:
    row, images = incident_row(path, **over)
    return incident_html(row, images, tz=TZ, generated_at=NOW, site="Test site")


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem.removeprefix("incident_"))
def test_an_incident_page_carries_everything_the_report_says(path: Path) -> None:
    fx = json.loads(path.read_text())
    report = fx["report"]
    html = render(path)
    assert escape(report["title"]) in html
    assert escape(report["summary"].split(".")[0]) in html
    assert fx["severity"].upper() in html and "Test site" in html
    for step in report["causal_chain"]:
        assert escape(step["description"]) in html  # what a browser or PDF shows
        for evidence_id in step["evidence"]:
            assert evidence_id in html  # every claim keeps its citation on paper
    for phase in report["phase_analysis"]:
        assert escape(phase["summary"]) in html
    for action in report["recommended_actions"]:
        assert escape(action["action"]) in html
    spans = {x["phase"]: x for x in fx["evidence"]["phase_timeline"]}
    for phase in report["phase_analysis"]:  # when each stage was, on the site's clock
        span = spans[phase["phase"]]
        start, end = (
            datetime.fromisoformat(span[k].replace("Z", "+00:00")).astimezone(TZ)
            for k in ("start", "end")
        )
        assert f"{start:%H:%M:%S} to {end:%H:%M:%S}" in html
    assert "What this report cannot tell" in html and "not a finding" in html
    assert html.count("<figure>") <= MAX_EVIDENCE_FRAMES
    assert "data:image/jpeg;base64," in html  # the pictures are inside the file


def test_text_from_a_model_cannot_inject_markup() -> None:
    row, images = incident_row(FIXTURES[1])
    row["report"] = {**row["report"], "summary": "<script>alert(1)</script> & more"}
    row["notes"] = '"quotes" and <b>bold</b>'
    html = incident_html(row, images, tz=TZ, generated_at=NOW, site='Site "A"')
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<b>bold</b>" not in html and "&lt;b&gt;bold&lt;/b&gt;" in html


def test_a_site_name_with_quotes_cannot_break_out_of_the_page_header() -> None:
    css = stylesheet(left='Site "A"\nline', right="r", footer="f")
    assert 'content: "Site \\"A\\" line"' in css


def test_evidence_frames_are_the_first_of_each_stage_and_view_then_the_rest_up_to_the_limit() -> (
    None
):
    evidence = {
        "phases": [
            {"phase": "baseline", "views": [{"frames": [{"uri": "a1"}, {"uri": "a2"}]}]},
            {"phase": "action", "views": [{"frames": [{"uri": "b1"}, {"uri": "b2"}]}]},
        ]
    }
    assert frame_uris(evidence) == ["a1", "b1", "a2", "b2"]
    assert frame_uris(evidence, limit=3) == ["a1", "b1", "a2"]
    assert frame_uris(None) == []


def test_the_provenance_sentence_matches_the_report_page() -> None:
    assert provenance_note(
        {
            "synthesis_model": "ollama/qwen2.5:3b",
            "tg": "rules",
            "fallback_used": True,
            "profile": "local",
        }
    ) == (
        "Report by ollama/qwen2.5:3b · phases from detector timing (the model could not place them)"
        " · local profile"
    )
    assert provenance_note({}) == "Provenance not recorded"


FACTS = {
    "date_from": "2026-10-06",
    "date_to": "2026-10-06",
    "timezone": "Asia/Kolkata",
    "events_total": 3,
    "events_rejected": 4,
    "by_type": {"crowding": 1, "loitering": 1, "intrusion": 1},
    "by_camera": {"bus-g331": 2, "bus-g340": 1},
    "by_severity": {"medium": 2, "high": 1},
    "by_hour": {"21": 3},
    "incidents_total": 1,
    "incidents": [
        {
            "id": "i1",
            "title": "Intrusion in Parking Lot",
            "severity": "high",
            "event_type": "intrusion",
            "cameras": ["bus-g340"],
            "at": "21:58",
        }
    ],
    "alerts_total": 3,
    "alerts_open": 0,
    "ack_p50_s": None,
    "ack_p90_s": None,
    "resolve_p50_s": 106,
    "resolve_p90_s": 115,
    "people_peak_by_camera": {"bus-g331": 15},
    "groups_total": 3,
    "groups_multi_camera": 0,
}


def test_a_daily_report_page_has_the_figures_the_narrative_may_cite() -> None:
    html = daily_html(
        {"facts": FACTS, "narrative": "Three events were verified.", "narrative_source": "llm"},
        tz=TZ, generated_at=NOW, site="Test site", profile="local",
    )  # fmt: skip
    for expected in (
        "Tuesday 06 October 2026",
        "Three events were verified.",
        "Intrusion in Parking Lot",
        "bus-g331",
        "1 min 46 s",
        "no data",
        "Verified events (4 false alarms rejected)",
    ):
        assert expected in html, expected
    assert "fixed template" not in html  # only said when it is true
    assert html.count("<rect") == 24 and "21:00, 3 events" in html  # one column per hour
    templated = daily_html(
        {"facts": FACTS, "narrative": "x", "narrative_source": "template"},
        tz=TZ, generated_at=NOW, site="s", profile="local",
    )  # fmt: skip
    assert "fixed template" in templated


# ---- the PDF itself -------------------------------------------------------------------------


def _weasyprint():
    try:
        import weasyprint
    except OSError as exc:  # the pango libraries are missing on this machine
        pytest.skip(f"WeasyPrint's system libraries are missing: {exc}")
    return weasyprint


def test_an_incident_becomes_an_a4_pdf_with_the_title_and_a_page_footer() -> None:
    weasyprint = _weasyprint()
    html = render(FIXTURES[1])
    pdf = html_to_pdf(html)
    assert pdf.startswith(b"%PDF-")
    document = weasyprint.HTML(string=html).render()
    assert len(document.pages) >= 1
    width, height = document.pages[0].width, document.pages[0].height
    assert (round(width / 96 * 25.4), round(height / 96 * 25.4)) == (210, 297)
    assert document.metadata.title == json.loads(FIXTURES[1].read_text())["report"]["title"]


def test_a_daily_report_becomes_a_pdf() -> None:
    _weasyprint()
    html = daily_html(
        {"facts": FACTS, "narrative": "Three events.", "narrative_source": "llm"},
        tz=TZ, generated_at=NOW, site="Test site", profile="local",
    )  # fmt: skip
    assert html_to_pdf(html).startswith(b"%PDF-")


# ---- a PDF that fails is not a failed report --------------------------------------------------


def _worker(**settings) -> ReasoningWorker:
    w = ReasoningWorker.__new__(ReasoningWorker)
    w._s = SimpleNamespace(
        pdf_enabled=True, reports_bucket="vms-reports", site_name="s", **settings
    )
    w._sessions = object()
    w._footage = object()
    w._tz = TZ
    w._profile = "local"
    return w


async def test_a_pdf_that_cannot_be_made_is_logged_and_does_not_raise(monkeypatch) -> None:
    async def boom(**_):
        raise OSError("pango is missing")

    monkeypatch.setattr(worker_module, "write_incident_pdf", boom)
    monkeypatch.setattr(worker_module, "write_daily_pdf", boom)
    w = _worker()
    await w._incident_pdf(uuid.uuid4())
    await w._daily_pdf(uuid.uuid4())  # neither raises


async def test_pdfs_can_be_switched_off(monkeypatch) -> None:
    calls = []

    async def spy(**kw):
        calls.append(kw)

    monkeypatch.setattr(worker_module, "write_incident_pdf", spy)
    off = _worker()
    off._s.pdf_enabled = False
    await off._incident_pdf(uuid.uuid4())
    assert calls == []
    await _worker()._incident_pdf(uuid.uuid4())
    assert len(calls) == 1 and calls[0]["bucket"] == "vms-reports"


def test_the_image_data_is_real_base64() -> None:
    row, images = incident_row(FIXTURES[1])
    html = incident_html(row, images, tz=TZ, generated_at=NOW, site="s")
    payload = html.split("data:image/jpeg;base64,")[1].split('"')[0]
    assert base64.b64decode(payload)[:2] == b"\xff\xd8"
