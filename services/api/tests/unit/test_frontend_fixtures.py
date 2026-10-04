"""The JSON the frontend's tests use is what the api really sends (P3-J4).

`frontend/src/features/alerts/fixtures/*.json` are built here from the real response models
(`AlertOut`, `AlertsPage`, `CorrelationGroupDetail`, `WsMessage`) and compared with the committed
files, so a change to the api's shape fails *this* test until the fixtures are regenerated, and the
frontend's own tests (zod against the same files) then fail if the UI no longer fits. Regenerate:

    UPDATE_FRONTEND_FIXTURES=1 uv run pytest services/api/tests/unit/test_frontend_fixtures.py
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from api.realtime.messages import WsMessage
from api.schemas import (
    AlertOut,
    AlertsPage,
    CorrelationGroupDetail,
)
from vms_db.models import Alert, CorrelationGroup, CorrelationLinkRow

FIXTURE_DIR = Path(__file__).resolve().parents[4] / "frontend/src/features/alerts/fixtures"

T0 = datetime(2026, 10, 5, 10, 15, 20, tzinfo=UTC)
GROUP_ID = uuid.UUID("0192f3e0-0001-7000-8000-00000000000a")
CAMERA_ID = uuid.UUID("01929e6c-0002-7000-8000-000000000002")


def _alert(n: int, **over: object) -> Alert:
    fields: dict[str, object] = {
        "id": uuid.UUID(f"0192f3d1-a{n:03d}-7000-8000-000000000001"),
        "event_id": f"0192f3d1-000{n}-7000-8000-00000000000{n}",
        "site_id": "rvce-campus",
        "camera_id": "cam02",
        "event_type": "intrusion",
        "severity": "high",
        "rule_id": "intrusion.after_hours",
        "zone_id": "01929e6c-0001-7000-8000-000000000001",
        "title": "Intrusion on cam02",
        "caption": "A person in a dark jacket climbs over the gate into the fenced area.",
        "verification_status": "verified",
        "confidence": 0.84,
        "start_ts": T0,
        "end_ts": T0 + timedelta(seconds=22),
        "keyframe_uris": [
            "s3://vms-keyframes/cam02/2026/10/05/10/000120/0004.jpg",
            "s3://vms-keyframes/cam02/2026/10/05/10/000121/0002.jpg",
        ],
        "group_id": GROUP_ID,
        "status": "open",
        "acknowledged_by": None,
        "acknowledged_at": None,
        "ack_note": None,
        "resolved_by": None,
        "resolved_at": None,
        "resolve_note": None,
        "created_at": T0 + timedelta(seconds=30),
        "updated_at": T0 + timedelta(seconds=30),
    }
    fields.update(over)
    return Alert(**fields)


def _group() -> CorrelationGroup:
    members = [
        {
            "event_id": "0192f3d1-0003-7000-8000-000000000003",
            "site_id": "rvce-campus",
            "camera_id": "cam03",
            "event_type": "abandoned_object",
            "severity": "high",
            "start_ts": (T0 - timedelta(seconds=20)).isoformat(),
            "end_ts": (T0 - timedelta(seconds=8)).isoformat(),
        },
        {
            "event_id": "0192f3d1-0001-7000-8000-000000000001",
            "site_id": "rvce-campus",
            "camera_id": "cam02",
            "event_type": "intrusion",
            "severity": "high",
            "start_ts": T0.isoformat(),
            "end_ts": (T0 + timedelta(seconds=22)).isoformat(),
        },
    ]
    return CorrelationGroup(
        id=GROUP_ID,
        site_id="rvce-campus",
        status="open",
        revision=2,
        start_ts=T0 - timedelta(seconds=20),
        end_ts=T0 + timedelta(seconds=22),
        max_severity="high",
        camera_ids=["cam03", "cam02"],
        event_types=["abandoned_object", "intrusion"],
        event_ids=[m["event_id"] for m in members],
        members=members,
        merged_into=None,
        publish_pending=False,
        created_at=T0 - timedelta(seconds=20),
        closed_at=None,
    )


def build() -> dict[str, object]:
    group = _group()
    urls = [
        "http://localhost:9000/vms-keyframes/cam02/2026/10/05/10/000120/0004.jpg?X-Amz-Expires=900",
        "http://localhost:9000/vms-keyframes/cam02/2026/10/05/10/000121/0002.jpg?X-Amz-Expires=900",
    ]
    open_alert = AlertOut.from_model(
        _alert(1), group=group, camera_id=CAMERA_ID, keyframe_urls=urls
    )
    acked = _alert(
        2,
        severity="critical",
        event_type="loitering",
        title="Loitering on cam02",
        status="acknowledged",
        acknowledged_by=uuid.UUID("01a0fe64-90f5-735f-ac6c-0caf54fbe756"),
        acknowledged_at=T0 + timedelta(minutes=1),
        ack_note="Guard sent to the north gate.",
        group_id=None,
        verification_status="skipped",
        caption=None,
        confidence=None,
        keyframe_uris=[],
    )
    acked_out = AlertOut.from_model(acked, camera_id=None)
    link = CorrelationLinkRow(
        group_id=GROUP_ID,
        from_event="0192f3d1-0003-7000-8000-000000000003",
        to_event="0192f3d1-0001-7000-8000-000000000001",
        edge_type="transit",
        delta_s=28.0,
        score=0.6973,
    )
    pushed = open_alert.model_copy(update={"keyframe_urls": []})
    return {
        "alert_open.json": open_alert.model_dump(mode="json"),
        "alert_acknowledged.json": acked_out.model_dump(mode="json"),
        "alerts_page.json": AlertsPage(
            items=[open_alert, acked_out], next_cursor="0192f3d1-a002-7000-8000-000000000001"
        ).model_dump(mode="json"),
        "correlation_group_detail.json": CorrelationGroupDetail.from_rows(group, [link]).model_dump(
            mode="json"
        ),
        "ws_alert_created.json": json.loads(
            WsMessage(
                type="alert.created",
                data=pushed.model_dump(mode="json"),
                ts=T0 + timedelta(seconds=30),
            ).to_json()
        ),
        "ws_alert_updated.json": json.loads(
            WsMessage(
                type="alert.updated",
                data=pushed.model_copy(
                    update={"status": "acknowledged", "ack_note": "On my way"}
                ).model_dump(mode="json"),
                ts=T0 + timedelta(seconds=75),
            ).to_json()
        ),
    }


@pytest.mark.parametrize("name", sorted(build()))
def test_the_committed_fixture_is_what_the_api_sends(name: str) -> None:
    expected = build()[name]
    path = FIXTURE_DIR / name
    if os.environ.get("UPDATE_FRONTEND_FIXTURES"):
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
    assert path.exists(), f"{name} missing: run with UPDATE_FRONTEND_FIXTURES=1"
    # Compared as data, not text: the frontend's formatter (Prettier) lays the file out its own
    # way, and layout is not part of what the api sends.
    assert json.loads(path.read_text()) == expected, (
        f"{name} no longer matches the api's response model; regenerate with "
        "UPDATE_FRONTEND_FIXTURES=1 and update the frontend if its tests then fail"
    )


def test_a_page_of_alerts_round_trips_through_the_response_model() -> None:
    """The fixture is also valid *input* to the model: nothing in it is shaped by hand."""
    page = (
        json.loads((FIXTURE_DIR / "alerts_page.json").read_text()) if FIXTURE_DIR.exists() else None
    )
    if page is None:
        pytest.skip("fixtures not generated yet")
    assert AlertsPage.model_validate(page).model_dump(mode="json") == page
