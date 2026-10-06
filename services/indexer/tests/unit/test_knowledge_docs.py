from datetime import UTC, datetime

from indexer.knowledge import event_doc, incident_docs
from vms_common.contracts.event import EventV1, Verification


def _event(caption, status="verified"):
    return EventV1(
        event_id="30b6f125-67c9-5eee-93ad-73d79e17268e",
        site_id="rvce-campus",
        camera_id="cam01",
        event_type="intrusion",
        severity="high",
        start_ts=datetime(2026, 10, 4, 6, 31, tzinfo=UTC),
        end_ts=datetime(2026, 10, 4, 6, 32, tzinfo=UTC),
        rule_id="intrusion.restricted",
        rule_score=0.9,
        zone_id="restricted-yard",
        verification=Verification(status=status, caption=caption),
    )


def test_an_event_is_indexed_by_its_caption_with_its_type_and_area():
    doc = event_doc(_event("A person walks near the gate."))
    assert "intrusion in restricted-yard on cam01" in doc.text and "walks near the gate" in doc.text
    assert doc.payload["doc_type"] == "event_caption" and doc.payload["camera_ids"] == ["cam01"]
    assert doc.payload["ts_end"] > doc.payload["ts_start"]


def test_an_event_without_a_caption_is_not_indexed_and_ids_are_stable():
    assert event_doc(_event(None, status="skipped")) is None
    assert event_doc(_event("x")).point_id == event_doc(_event("x")).point_id


def test_an_incident_becomes_one_document_per_section():
    report = {
        "title": "Man at gate",
        "summary": "A man waits at the gate.",
        "phase_analysis": [{"phase": "action", "summary": "He climbs."}],
        "causal_chain": [{"step": 1, "description": "Gate left open."}],
        "recommended_actions": [{"action": "Lock the gate"}],
    }
    docs = incident_docs(
        "i1",
        report,
        camera_ids=["cam01"],
        start=datetime(2026, 10, 4, tzinfo=UTC),
        end=datetime(2026, 10, 4, 0, 1, tzinfo=UTC),
        severity="high",
        event_type="intrusion",
    )
    assert [d.payload["part"] for d in docs] == ["summary", "phase:action", "causal", "actions"]
    assert all(d.text.startswith("Man at gate.") for d in docs)
    assert len({d.point_id for d in docs}) == 4
