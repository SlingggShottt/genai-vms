"""Alerts over a real Postgres, Redis and S3 double (P3-J3): the REST surface (list, read,
acknowledge, resolve), audit, and the two consumers' handlers. Run via `make test-int`."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from api.consumers.alerts import AlertEventConsumer, AlertGroupConsumer
from api.notifiers import AlertNotice, NotificationDispatcher
from api.realtime.hub import ConnectionHub
from api.realtime.relay import RedisRelay
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from vms_common.contracts.correlation import CorrelationV1
from vms_common.contracts.event import EventV1
from vms_db.models import Alert, AuditLog, CorrelationGroup
from vms_db.session import session_scope

pytestmark = pytest.mark.integration

Headers = Callable[[str], dict[str, str]]
SeedAlert = Callable[..., Awaitable[Alert]]
SeedGroup = Callable[..., Awaitable[CorrelationGroup]]


# --- helpers -------------------------------------------------------------------------------------


@pytest.fixture
def operator(make_user: Callable[[str], dict[str, str]]) -> dict[str, str]:
    return make_user("operator")


@pytest.fixture
def viewer(make_user: Callable[[str], dict[str, str]]) -> dict[str, str]:
    return make_user("viewer")


def get(client: TestClient, headers: dict[str, str], path: str, **params: Any):
    return client.get(f"/api/v1{path}", headers=headers, params=params)


def post(client: TestClient, headers: dict[str, str], path: str, body: Any = None):
    return client.post(f"/api/v1{path}", headers=headers, json=body)


async def audit_rows(factory: async_sessionmaker, alert_id: uuid.UUID | str) -> list[AuditLog]:
    async with factory() as session:
        rows = await session.execute(
            select(AuditLog)
            .where(AuditLog.entity_id == str(alert_id))
            .order_by(AuditLog.created_at)
        )
        return list(rows.scalars())


# --- listing and reading -------------------------------------------------------------------------


async def test_an_operator_lists_alerts_newest_first_with_everything_the_tray_needs(
    client: TestClient, operator: dict, auth_headers: Headers, seed_alert: SeedAlert, unique_camera
) -> None:
    older = await seed_alert(camera=unique_camera, severity="medium")
    newer = await seed_alert(camera=unique_camera, severity="critical", event_type="loitering")

    body = get(client, auth_headers(operator["token"]), "/alerts", camera_id=unique_camera).json()

    assert [a["id"] for a in body["items"]] == [str(newer.id), str(older.id)]
    assert body["next_cursor"] is None
    first = body["items"][0]
    assert first["camera_code"] == unique_camera
    assert first["event_type"] == "loitering" and first["severity"] == "critical"
    assert first["status"] == "open"
    assert first["title"] == f"Loitering on {unique_camera}"
    assert first["verification_status"] == "verified" and first["caption"]
    assert first["group"] is None and first["acknowledged_at"] is None
    assert first["event_id"] == newer.event_id


async def test_keyframes_are_presigned_per_request_and_never_stored_as_urls(
    client: TestClient,
    operator: dict,
    auth_headers: Headers,
    seed_alert: SeedAlert,
    unique_camera,
    db_session_factory: async_sessionmaker,
) -> None:
    alert = await seed_alert(camera=unique_camera, keyframes=2)

    detail = get(client, auth_headers(operator["token"]), f"/alerts/{alert.id}").json()

    assert detail["keyframe_count"] == 2 and len(detail["keyframe_urls"]) == 2
    for url, uri in zip(detail["keyframe_urls"], alert.keyframe_uris, strict=True):
        assert url.startswith("http") and uri.removeprefix("s3://vms-keyframes/") in url
        assert "X-Amz-Expires=900" in url  # 15 minutes (NFR-SEC-02)
    async with db_session_factory() as session:
        stored = (await session.get(Alert, alert.id)).keyframe_uris
    assert stored == alert.keyframe_uris and all(u.startswith("s3://") for u in stored)


async def test_the_camera_id_links_to_the_configured_camera_when_there_is_one(
    client: TestClient,
    operator: dict,
    admin_access_token: str,
    auth_headers: Headers,
    seed_alert: SeedAlert,
    unique_camera,
) -> None:
    created = client.post(
        "/api/v1/cameras",
        headers=auth_headers(admin_access_token),
        json={
            "code": unique_camera,
            "name": "Alert test camera",
            "rtsp_url": "rtsp://mediamtx:8554/x",
            "site_id": "rvce-campus",
        },
    )
    assert created.status_code == 201, created.text
    alert = await seed_alert(camera=unique_camera)
    orphan = await seed_alert(camera=f"{unique_camera}-gone")

    headers = auth_headers(operator["token"])
    assert get(client, headers, f"/alerts/{alert.id}").json()["camera_id"] == created.json()["id"]
    assert get(client, headers, f"/alerts/{orphan.id}").json()["camera_id"] is None


async def test_cursor_pagination_walks_every_alert_exactly_once(
    client: TestClient, operator: dict, auth_headers: Headers, seed_alert: SeedAlert, unique_camera
) -> None:
    seeded = [str((await seed_alert(camera=unique_camera)).id) for _ in range(5)]
    headers = auth_headers(operator["token"])

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, Any] = {"camera_id": unique_camera, "limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = get(client, headers, "/alerts", **params).json()
        pages += 1
        seen += [a["id"] for a in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert pages == 3
    assert seen == list(reversed(seeded))  # newest first, none twice, none missed


async def test_the_list_filters(
    client: TestClient, operator: dict, auth_headers: Headers, seed_alert: SeedAlert, unique_camera
) -> None:
    other_camera = f"{unique_camera}-b"
    base = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    open_high = await seed_alert(camera=unique_camera, severity="high", start_ts=base)
    acked_low = await seed_alert(
        camera=unique_camera,
        severity="low",
        status="acknowledged",
        start_ts=base + timedelta(hours=1),
    )
    done_crit = await seed_alert(
        camera=unique_camera,
        severity="critical",
        status="resolved",
        start_ts=base + timedelta(hours=2),
    )
    elsewhere = await seed_alert(camera=other_camera, severity="high", start_ts=base)
    # exactly on the window's start: included (the end is exclusive: `done_crit` sits on it)
    on_start = await seed_alert(
        camera=unique_camera,
        severity="medium",
        status="acknowledged",
        start_ts=base + timedelta(minutes=30),
    )
    headers = auth_headers(operator["token"])

    def ids(**params: Any) -> set[str]:
        body = get(client, headers, "/alerts", **params).json()
        assert body["next_cursor"] is None
        return {a["id"] for a in body["items"]}

    mine = {str(open_high.id), str(acked_low.id), str(done_crit.id), str(on_start.id)}
    assert ids(camera_id=unique_camera) == mine
    assert ids(camera_id=other_camera) == {str(elsewhere.id)}
    assert ids(camera_id=unique_camera, status="open") == {str(open_high.id)}
    assert ids(camera_id=unique_camera, status=["open", "resolved"]) == {
        str(open_high.id),
        str(done_crit.id),
    }
    assert ids(camera_id=unique_camera, severity="critical") == {str(done_crit.id)}
    assert ids(camera_id=unique_camera, severity=["low", "high"]) == {
        str(open_high.id),
        str(acked_low.id),
    }
    # start <= event start < end
    window = {
        "camera_id": unique_camera,
        "start": (base + timedelta(minutes=30)).isoformat(),
        "end": (base + timedelta(hours=2)).isoformat(),
    }
    assert ids(**window) == {str(acked_low.id), str(on_start.id)}
    assert ids(camera_id=unique_camera, status="open", severity="low") == set()


async def test_filtering_by_correlation_group(
    client: TestClient,
    operator: dict,
    auth_headers: Headers,
    seed_alert: SeedAlert,
    seed_group: SeedGroup,
    unique_camera,
    db_session_factory: async_sessionmaker,
) -> None:
    grouped = await seed_alert(camera=unique_camera)
    lone = await seed_alert(camera=unique_camera)
    group = await seed_group(event_ids=[grouped.event_id])
    async with session_scope(db_session_factory) as session:
        await session.execute(
            text("UPDATE core.alerts SET group_id = :g WHERE id = :id"),
            {"g": group.id, "id": grouped.id},
        )

    body = get(client, auth_headers(operator["token"]), "/alerts", group_id=str(group.id)).json()

    assert [a["id"] for a in body["items"]] == [str(grouped.id)]
    assert str(lone.id) not in {a["id"] for a in body["items"]}


async def test_an_alert_shows_its_group_and_follows_a_merge_to_the_survivor(
    client: TestClient,
    operator: dict,
    auth_headers: Headers,
    seed_alert: SeedAlert,
    seed_group: SeedGroup,
    unique_camera,
    db_session_factory: async_sessionmaker,
) -> None:
    alert = await seed_alert(camera=unique_camera, severity="high")
    other = str(uuid.uuid4())
    survivor = await seed_group(
        event_ids=[alert.event_id, other], cameras=(unique_camera, "cam09"), severity="critical"
    )
    merged_away = await seed_group(
        event_ids=[alert.event_id], status="merged", merged_into=survivor.id
    )
    async with session_scope(db_session_factory) as session:  # the alert still points at the old id
        await session.execute(
            text("UPDATE core.alerts SET group_id = :g WHERE id = :id"),
            {"g": merged_away.id, "id": alert.id},
        )

    shown = get(client, auth_headers(operator["token"]), f"/alerts/{alert.id}").json()["group"]

    assert shown["id"] == str(survivor.id)  # not the dead group
    assert shown["event_count"] == 2 and shown["max_severity"] == "critical"
    assert shown["camera_ids"] == [unique_camera, "cam09"] and shown["status"] == "open"


async def test_unknown_and_malformed_ids_and_bad_queries(
    client: TestClient, operator: dict, auth_headers: Headers
) -> None:
    headers = auth_headers(operator["token"])
    missing = get(client, headers, f"/alerts/{uuid.uuid4()}")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "NOT_FOUND"
    assert get(client, headers, "/alerts/not-a-uuid").status_code == 400
    for params in (
        {"status": "closed"},
        {"severity": "urgent"},
        {"limit": 0},
        {"limit": 201},
        {"cursor": "nope"},
        {"group_id": "nope"},
        {"start": "2026-03-02T00:00:00Z", "end": "2026-03-01T00:00:00Z"},
    ):
        response = get(client, headers, "/alerts", **params)
        assert response.status_code == 400, (params, response.text)
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --- acknowledge / resolve -----------------------------------------------------------------------


async def test_an_operator_acknowledges_with_a_note_and_it_is_audited(
    client: TestClient,
    operator: dict,
    auth_headers: Headers,
    seed_alert: SeedAlert,
    unique_camera,
    db_session_factory: async_sessionmaker,
) -> None:
    alert = await seed_alert(camera=unique_camera)
    headers = auth_headers(operator["token"])

    response = post(client, headers, f"/alerts/{alert.id}/ack", {"note": "  on my way  "})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "acknowledged"
    assert body["acknowledged_by"] == operator["id"] and body["acknowledged_at"]
    assert body["ack_note"] == "on my way"  # trimmed
    assert body["resolved_at"] is None and len(body["keyframe_urls"]) == 2
    assert get(client, headers, f"/alerts/{alert.id}").json()["status"] == "acknowledged"

    (entry,) = await audit_rows(db_session_factory, alert.id)
    assert entry.action == "alert.acknowledged" and str(entry.user_id) == operator["id"]
    assert entry.entity_type == "alert"
    assert entry.details == {
        "event_id": alert.event_id,
        "camera": unique_camera,
        "note": "on my way",
    }


async def test_resolving_after_an_acknowledgement_keeps_both_records(
    client: TestClient,
    operator: dict,
    admin_access_token: str,
    auth_headers: Headers,
    seed_alert: SeedAlert,
    unique_camera,
    db_session_factory: async_sessionmaker,
) -> None:
    alert = await seed_alert(camera=unique_camera)
    post(client, auth_headers(operator["token"]), f"/alerts/{alert.id}/ack", {"note": "looking"})

    resolved = post(  # a different person may close it
        client,
        auth_headers(admin_access_token),
        f"/alerts/{alert.id}/resolve",
        {"note": "guard sent"},
    ).json()

    assert resolved["status"] == "resolved"
    assert resolved["acknowledged_by"] == operator["id"] and resolved["ack_note"] == "looking"
    assert resolved["resolved_by"] and resolved["resolved_by"] != operator["id"]
    assert resolved["resolve_note"] == "guard sent" and resolved["resolved_at"]
    actions = [r.action for r in await audit_rows(db_session_factory, alert.id)]
    assert actions == ["alert.acknowledged", "alert.resolved"]


async def test_an_alert_can_be_resolved_without_being_acknowledged_first(
    client: TestClient, operator: dict, auth_headers: Headers, seed_alert: SeedAlert, unique_camera
) -> None:
    alert = await seed_alert(camera=unique_camera)

    body = post(client, auth_headers(operator["token"]), f"/alerts/{alert.id}/resolve").json()

    assert body["status"] == "resolved" and body["resolved_at"]
    assert body["acknowledged_at"] is None and body["resolve_note"] is None


@pytest.mark.parametrize(
    ("start_status", "action", "expected"),
    [
        ("acknowledged", "ack", "acknowledged"),
        ("resolved", "ack", "resolved"),
        ("resolved", "resolve", "resolved"),
    ],
)
async def test_an_action_the_alert_is_past_is_a_409_naming_its_status(
    client: TestClient,
    operator: dict,
    auth_headers: Headers,
    seed_alert: SeedAlert,
    unique_camera,
    db_session_factory: async_sessionmaker,
    start_status: str,
    action: str,
    expected: str,
) -> None:
    alert = await seed_alert(camera=unique_camera, status=start_status)

    response = post(client, auth_headers(operator["token"]), f"/alerts/{alert.id}/{action}")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "CONFLICT" and error["details"] == {"status": expected}
    assert expected in error["message"]
    assert await audit_rows(db_session_factory, alert.id) == []  # a refused action leaves no trace


async def test_acting_on_an_unknown_alert_is_404_and_a_malformed_id_is_400(
    client: TestClient, operator: dict, auth_headers: Headers
) -> None:
    headers = auth_headers(operator["token"])
    for action in ("ack", "resolve"):
        assert post(client, headers, f"/alerts/{uuid.uuid4()}/{action}").status_code == 404
        assert post(client, headers, f"/alerts/xyz/{action}").status_code == 400


async def test_notes_are_optional_trimmed_and_bounded(
    client: TestClient, operator: dict, auth_headers: Headers, seed_alert: SeedAlert, unique_camera
) -> None:
    headers = auth_headers(operator["token"])
    blank = await seed_alert(camera=unique_camera)
    assert (
        post(client, headers, f"/alerts/{blank.id}/ack", {"note": "   "}).json()["ack_note"] is None
    )
    nobody = await seed_alert(camera=unique_camera)
    assert post(client, headers, f"/alerts/{nobody.id}/ack").status_code == 200  # no body at all
    alert = await seed_alert(camera=unique_camera)
    for bad in ({"note": "x" * 1001}, {"note": 5}, {"remark": "typo"}):
        response = post(client, headers, f"/alerts/{alert.id}/ack", bad)
        assert response.status_code == 400, (bad, response.text)
    assert (
        get(client, headers, f"/alerts/{alert.id}").json()["status"] == "open"
    )  # none took effect
    assert post(client, headers, f"/alerts/{alert.id}/ack", {"note": "x" * 1000}).status_code == 200


async def test_concurrent_acknowledgements_have_exactly_one_winner(
    client: TestClient,
    operator: dict,
    auth_headers: Headers,
    seed_alert: SeedAlert,
    unique_camera,
    db_session_factory: async_sessionmaker,
) -> None:
    alert = await seed_alert(camera=unique_camera)
    headers = auth_headers(operator["token"])

    def ack(_: int) -> int:
        return post(client, headers, f"/alerts/{alert.id}/ack", {"note": "me"}).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = sorted(pool.map(ack, range(8)))

    assert codes == [200] + [409] * 7
    assert len(await audit_rows(db_session_factory, alert.id)) == 1


async def test_a_viewer_sees_no_alerts_and_can_do_nothing_to_them(
    client: TestClient, viewer: dict, auth_headers: Headers, seed_alert: SeedAlert, unique_camera
) -> None:
    alert = await seed_alert(camera=unique_camera)
    headers = auth_headers(viewer["token"])
    assert get(client, headers, "/alerts").status_code == 403
    assert get(client, headers, f"/alerts/{alert.id}").status_code == 403
    assert post(client, headers, f"/alerts/{alert.id}/ack").status_code == 403
    assert post(client, headers, f"/alerts/{alert.id}/resolve").status_code == 403


# --- correlation groups over REST ----------------------------------------------------------------


async def test_correlation_groups_are_readable_by_every_role_with_members_and_links(
    client: TestClient,
    viewer: dict,
    auth_headers: Headers,
    seed_group: SeedGroup,
    db_session_factory: async_sessionmaker,
) -> None:
    from vms_db.models import CorrelationLinkRow  # noqa: PLC0415

    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    group = await seed_group(event_ids=[a, b], cameras=("cam02", "cam04"))
    async with session_scope(db_session_factory) as session:
        session.add(
            CorrelationLinkRow(
                group_id=group.id,
                from_event=a,
                to_event=b,
                edge_type="transit",
                delta_s=31.5,
                score=0.69731,
            )
        )
    headers = auth_headers(viewer["token"])

    detail = get(client, headers, f"/correlations/{group.id}")

    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["id"] == str(group.id) and body["status"] == "open" and body["revision"] == 1
    assert {m["event_id"] for m in body["members"]} == {a, b}
    assert body["links"] == [
        {"from_event": a, "to_event": b, "edge_type": "transit", "delta_s": 31.5, "score": 0.6973}
    ]
    listed = get(client, headers, "/correlations", limit=200).json()
    assert str(group.id) in {g["id"] for g in listed["items"]}


async def test_the_correlation_list_hides_merged_groups_unless_asked_and_filters_by_time(
    client: TestClient, operator: dict, auth_headers: Headers, seed_group: SeedGroup
) -> None:
    survivor = await seed_group(event_ids=[str(uuid.uuid4())])
    merged = await seed_group(
        event_ids=[str(uuid.uuid4())], status="merged", merged_into=survivor.id
    )
    headers = auth_headers(operator["token"])

    default = {g["id"] for g in get(client, headers, "/correlations", limit=200).json()["items"]}
    assert str(survivor.id) in default and str(merged.id) not in default

    asked = get(client, headers, "/correlations", status="merged", limit=200).json()["items"]
    assert str(merged.id) in {g["id"] for g in asked}
    one = get(client, headers, f"/correlations/{merged.id}").json()  # a link to it still works
    assert one["status"] == "merged" and one["merged_into"] == str(survivor.id)

    nowhere = get(
        client, headers, "/correlations", start="2001-01-01T00:00:00Z", end="2001-01-02T00:00:00Z"
    ).json()
    assert nowhere["items"] == []
    later = get(
        client, headers, "/correlations", start="2099-01-01T00:00:00Z", end="2099-01-02T00:00:00Z"
    ).json()
    assert later["items"] == []  # a window after every group excludes them too
    assert get(client, headers, f"/correlations/{uuid.uuid4()}").status_code == 404
    assert get(client, headers, "/correlations/xyz").status_code == 400


# --- the event consumer --------------------------------------------------------------------------


class RecordingNotifier:
    name = "recorder"

    def __init__(self) -> None:
        self.notices: list[AlertNotice] = []

    async def send(self, notice: AlertNotice) -> None:
        self.notices.append(notice)


class ExplodingNotifier:
    name = "exploding"

    async def send(self, notice: AlertNotice) -> None:
        raise RuntimeError("smtp is down")


def event_from_fixture(fixtures_dir: Path, name: str, **over: Any) -> EventV1:
    raw = json.loads((fixtures_dir / f"event_v1_{name}.json").read_text())
    raw["event_id"] = str(uuid.uuid4())  # the db is shared by the whole session
    raw.update(over)
    return EventV1.model_validate(raw)


def event_consumer(
    factory: async_sessionmaker,
    *notifiers: Any,
    min_severity: str = "medium",
    now: datetime | None = None,
    max_age_s: float = 900.0,
) -> AlertEventConsumer:
    return AlertEventConsumer(
        topic="vms.events.v1",
        group_id="api-alerts-test",
        bootstrap_servers="unused:9092",
        session_factory=factory,
        dispatcher=NotificationDispatcher(list(notifiers), timeout_s=2.0),
        min_severity=min_severity,
        notify_max_age_s=max_age_s,
        clock=lambda: now or datetime(2026, 10, 5, 10, 16, 0, tzinfo=UTC),
    )


async def alerts_for(factory: async_sessionmaker, event_id: str) -> list[Alert]:
    async with factory() as session:
        return list(
            (await session.execute(select(Alert).where(Alert.event_id == event_id))).scalars()
        )


async def test_a_verified_event_becomes_an_alert_and_is_announced(
    db_session_factory: async_sessionmaker, fixtures_dir: Path, unique_camera
) -> None:
    event = event_from_fixture(fixtures_dir, "intrusion", camera_id=unique_camera)
    notifier = RecordingNotifier()

    await event_consumer(db_session_factory, notifier).handle(event, None)  # type: ignore[arg-type]

    (alert,) = await alerts_for(db_session_factory, event.event_id)
    assert alert.status == "open" and alert.severity == "high"
    assert alert.camera_id == unique_camera and alert.event_type == "intrusion"
    assert alert.title == f"Intrusion on {unique_camera}"
    assert alert.caption == event.verification.caption
    assert alert.verification_status == "verified" and alert.confidence == 0.84
    assert alert.rule_id == "intrusion.after_hours" and alert.zone_id == event.zone_id
    assert alert.keyframe_uris == event.keyframe_uris and alert.group_id is None
    assert (alert.start_ts, alert.end_ts) == (event.start_ts, event.end_ts)
    (notice,) = notifier.notices
    assert notice.alert_id == str(alert.id) and notice.severity == "high"
    assert notice.payload["id"] == str(alert.id) and notice.payload["keyframe_urls"] == []
    assert notice.payload["keyframe_count"] == 2


async def test_an_event_below_the_threshold_raises_nothing(
    db_session_factory: async_sessionmaker, fixtures_dir: Path, unique_camera
) -> None:
    quiet = event_from_fixture(fixtures_dir, "running_skipped", camera_id=unique_camera)  # low
    notifier = RecordingNotifier()
    consumer = event_consumer(db_session_factory, notifier, min_severity="medium")

    await consumer.handle(quiet, None)  # type: ignore[arg-type]

    assert await alerts_for(db_session_factory, quiet.event_id) == []
    assert notifier.notices == []
    # the same event is an alert when the bar is lowered
    await event_consumer(db_session_factory, notifier, min_severity="low").handle(quiet, None)  # type: ignore[arg-type]
    (alert,) = await alerts_for(db_session_factory, quiet.event_id)
    assert alert.verification_status == "skipped" and alert.caption is None
    assert alert.confidence is None


@pytest.mark.parametrize(
    ("min_severity", "severity", "alerts"),
    [
        ("high", "medium", False),
        ("high", "high", True),
        ("high", "critical", True),
        ("critical", "high", False),
        ("low", "low", True),
    ],
)
async def test_the_severity_threshold_is_inclusive(
    db_session_factory: async_sessionmaker,
    fixtures_dir: Path,
    unique_camera,
    min_severity: str,
    severity: str,
    alerts: bool,
) -> None:
    event = event_from_fixture(
        fixtures_dir, "intrusion", camera_id=unique_camera, severity=severity
    )
    await event_consumer(db_session_factory, min_severity=min_severity).handle(event, None)  # type: ignore[arg-type]
    assert bool(await alerts_for(db_session_factory, event.event_id)) is alerts


async def test_a_redelivered_event_adds_no_second_alert_and_no_second_announcement(
    db_session_factory: async_sessionmaker, fixtures_dir: Path, unique_camera
) -> None:
    event = event_from_fixture(fixtures_dir, "intrusion", camera_id=unique_camera)
    notifier = RecordingNotifier()
    consumer = event_consumer(db_session_factory, notifier)

    for _ in range(3):
        await consumer.handle(event, None)  # type: ignore[arg-type]

    assert len(await alerts_for(db_session_factory, event.event_id)) == 1
    assert len(notifier.notices) == 1


async def test_two_consumers_racing_on_one_event_make_exactly_one_alert(
    db_session_factory: async_sessionmaker, fixtures_dir: Path, unique_camera
) -> None:
    event = event_from_fixture(fixtures_dir, "intrusion", camera_id=unique_camera)
    notifier = RecordingNotifier()

    await asyncio.gather(
        *(event_consumer(db_session_factory, notifier).handle(event, None) for _ in range(6))  # type: ignore[arg-type]
    )

    assert len(await alerts_for(db_session_factory, event.event_id)) == 1
    assert len(notifier.notices) == 1


async def test_a_failing_channel_does_not_fail_the_message_or_lose_the_alert(
    db_session_factory: async_sessionmaker, fixtures_dir: Path, unique_camera
) -> None:
    event = event_from_fixture(fixtures_dir, "intrusion", camera_id=unique_camera)
    good = RecordingNotifier()

    await event_consumer(db_session_factory, ExplodingNotifier(), good).handle(event, None)  # type: ignore[arg-type]

    assert len(await alerts_for(db_session_factory, event.event_id)) == 1
    assert len(good.notices) == 1


async def test_an_old_event_is_stored_but_not_announced(
    db_session_factory: async_sessionmaker, fixtures_dir: Path, unique_camera
) -> None:
    """A fresh consumer group replays the topic: history must not email anyone."""
    event = event_from_fixture(fixtures_dir, "intrusion", camera_id=unique_camera)
    notifier = RecordingNotifier()
    long_after = event.end_ts + timedelta(days=30)

    await event_consumer(db_session_factory, notifier, now=long_after).handle(event, None)  # type: ignore[arg-type]

    assert len(await alerts_for(db_session_factory, event.event_id)) == 1
    assert notifier.notices == []
    # one second inside the window is still announced
    recent = event_from_fixture(fixtures_dir, "intrusion", camera_id=unique_camera)
    await event_consumer(
        db_session_factory, notifier, now=recent.end_ts + timedelta(seconds=900), max_age_s=900
    ).handle(recent, None)  # type: ignore[arg-type]
    assert len(notifier.notices) == 1


async def test_an_event_correlation_already_grouped_gets_its_group_at_creation(
    db_session_factory: async_sessionmaker, fixtures_dir: Path, seed_group: SeedGroup, unique_camera
) -> None:
    event = event_from_fixture(fixtures_dir, "intrusion", camera_id=unique_camera)
    group = await seed_group(event_ids=[event.event_id])

    await event_consumer(db_session_factory).handle(event, None)  # type: ignore[arg-type]

    (alert,) = await alerts_for(db_session_factory, event.event_id)
    assert alert.group_id == group.id


async def test_a_merged_away_group_is_not_chosen_for_a_new_alert(
    db_session_factory: async_sessionmaker, fixtures_dir: Path, seed_group: SeedGroup, unique_camera
) -> None:
    event = event_from_fixture(fixtures_dir, "intrusion", camera_id=unique_camera)
    survivor = await seed_group(event_ids=[event.event_id, str(uuid.uuid4())])
    await seed_group(event_ids=[event.event_id], status="merged", merged_into=survivor.id)
    async with session_scope(db_session_factory) as session:
        # A new row version goes to the end of the heap, so the merged group is now the first
        # row a scan meets: only the status filter can keep it from being chosen.
        await session.execute(
            text("UPDATE events.correlation_groups SET revision = revision + 1 WHERE id = :id"),
            {"id": survivor.id},
        )

    await event_consumer(db_session_factory).handle(event, None)  # type: ignore[arg-type]

    (alert,) = await alerts_for(db_session_factory, event.event_id)
    assert alert.group_id == survivor.id


# --- the correlation consumer --------------------------------------------------------------------


def correlation_message(fixtures_dir: Path, **over: Any) -> CorrelationV1:
    raw = json.loads((fixtures_dir / "correlation_v1.json").read_text())
    raw.update({"status": "open", "links": [], "merged_into": None, "revision": 1})
    raw.update(over)
    return CorrelationV1.model_validate(raw)


@pytest.fixture
async def live_hub(redis_client):
    """A relay feeding a hub with one operator and one viewer connected, as a replica would."""
    hub = ConnectionHub()
    relay = RedisRelay(redis_client, hub)
    task = asyncio.create_task(relay.run())
    await asyncio.sleep(0.3)
    try:
        yield relay, hub, hub.connect("operator"), hub.connect("viewer")
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def group_consumer(factory: async_sessionmaker, relay: RedisRelay) -> AlertGroupConsumer:
    return AlertGroupConsumer(
        topic="vms.correlations.v1",
        group_id="api-alerts-correlations-test",
        bootstrap_servers="unused:9092",
        session_factory=factory,
        relay=relay,
    )


async def alert_group(factory: async_sessionmaker, alert_id: uuid.UUID) -> uuid.UUID | None:
    async with factory() as session:
        return (await session.get(Alert, alert_id)).group_id


async def test_a_correlation_message_groups_the_alerts_of_its_events_and_tells_the_dashboards(
    db_session_factory: async_sessionmaker,
    fixtures_dir: Path,
    seed_alert: SeedAlert,
    seed_group: SeedGroup,
    live_hub,
    unique_camera,
) -> None:
    relay, _hub, operator_socket, viewer_socket = live_hub
    inside = [await seed_alert(camera=unique_camera) for _ in range(2)]
    outside = await seed_alert(camera=unique_camera)
    group = await seed_group(event_ids=[a.event_id for a in inside])
    message = correlation_message(
        fixtures_dir,
        group_id=str(group.id),
        event_ids=[a.event_id for a in inside],
        camera_ids=[unique_camera],
    )

    await group_consumer(db_session_factory, relay).handle(message, None)  # type: ignore[arg-type]

    assert [await alert_group(db_session_factory, a.id) for a in inside] == [group.id] * 2
    assert await alert_group(db_session_factory, outside.id) is None
    pushed = [json.loads(await asyncio.wait_for(operator_socket.queue.get(), 5)) for _ in range(2)]
    assert {p["type"] for p in pushed} == {"alert.updated"}
    assert {p["data"]["id"] for p in pushed} == {str(a.id) for a in inside}
    assert all(p["data"]["group"]["id"] == str(group.id) for p in pushed)
    assert all(p["data"]["keyframe_urls"] == [] for p in pushed)  # no urls on a shared channel
    assert operator_socket.queue.empty() and viewer_socket.queue.empty()  # viewers never see alerts


async def test_repeating_a_correlation_message_changes_and_announces_nothing(
    db_session_factory: async_sessionmaker,
    fixtures_dir: Path,
    seed_alert: SeedAlert,
    seed_group: SeedGroup,
    live_hub,
    unique_camera,
) -> None:
    relay, _hub, operator_socket, _viewer = live_hub
    alert = await seed_alert(camera=unique_camera)
    group = await seed_group(event_ids=[alert.event_id])
    message = correlation_message(
        fixtures_dir, group_id=str(group.id), event_ids=[alert.event_id], camera_ids=[unique_camera]
    )
    consumer = group_consumer(db_session_factory, relay)

    await consumer.handle(message, None)  # type: ignore[arg-type]
    await asyncio.wait_for(operator_socket.queue.get(), 5)
    await consumer.handle(message, None)  # type: ignore[arg-type]  # redelivered
    await asyncio.sleep(0.3)

    assert operator_socket.queue.empty()
    assert await alert_group(db_session_factory, alert.id) == group.id


async def test_a_merge_moves_the_alerts_to_the_survivor(
    db_session_factory: async_sessionmaker,
    fixtures_dir: Path,
    seed_alert: SeedAlert,
    seed_group: SeedGroup,
    live_hub,
    unique_camera,
) -> None:
    relay, _hub, operator_socket, _viewer = live_hub
    kept = await seed_alert(camera=unique_camera)  # already in the survivor: must not be touched
    by_group = await seed_alert(
        camera=unique_camera
    )  # in the absorbed group, not named by the message
    by_event = await seed_alert(camera=unique_camera)  # named by the message, group never recorded
    both = await seed_alert(camera=unique_camera)  # in the absorbed group and named by the message
    survivor = await seed_group(event_ids=[a.event_id for a in (kept, by_group, by_event, both)])
    absorbed = await seed_group(event_ids=[both.event_id], status="merged", merged_into=survivor.id)
    async with session_scope(db_session_factory) as session:
        for alert, group in ((kept, survivor), (by_group, absorbed), (both, absorbed)):
            await session.execute(
                text("UPDATE core.alerts SET group_id = :g WHERE id = :id"),
                {"g": group.id, "id": alert.id},
            )
    message = correlation_message(
        fixtures_dir,
        group_id=str(absorbed.id),
        status="merged",
        merged_into=str(survivor.id),
        event_ids=[both.event_id, by_event.event_id],
        camera_ids=[unique_camera],
    )

    await group_consumer(db_session_factory, relay).handle(message, None)  # type: ignore[arg-type]

    for alert in (kept, by_group, by_event, both):
        assert await alert_group(db_session_factory, alert.id) == survivor.id
    pushed = [json.loads(await asyncio.wait_for(operator_socket.queue.get(), 5)) for _ in range(3)]
    assert {p["data"]["id"] for p in pushed} == {str(a.id) for a in (by_group, by_event, both)}
    assert all(p["data"]["group"]["id"] == str(survivor.id) for p in pushed)
    await asyncio.sleep(0.2)
    assert operator_socket.queue.empty()  # `kept` was already right: no push for it


async def test_a_stale_open_message_cannot_undo_a_merge(
    db_session_factory: async_sessionmaker,
    fixtures_dir: Path,
    seed_alert: SeedAlert,
    seed_group: SeedGroup,
    live_hub,
    unique_camera,
) -> None:
    """Kafka may deliver an old `open` message after the `merged` one."""
    relay, _hub, _operator, _viewer = live_hub
    alert = await seed_alert(camera=unique_camera)
    survivor = await seed_group(event_ids=[alert.event_id])
    absorbed = await seed_group(
        event_ids=[alert.event_id], status="merged", merged_into=survivor.id
    )
    async with session_scope(db_session_factory) as session:
        await session.execute(
            text("UPDATE core.alerts SET group_id = :g WHERE id = :id"),
            {"g": survivor.id, "id": alert.id},
        )
    stale = correlation_message(
        fixtures_dir,
        group_id=str(absorbed.id),
        status="open",
        revision=1,
        event_ids=[alert.event_id],
        camera_ids=[unique_camera],
    )

    await group_consumer(db_session_factory, relay).handle(stale, None)  # type: ignore[arg-type]

    assert await alert_group(db_session_factory, alert.id) == survivor.id


async def test_a_message_naming_no_known_alert_is_a_quiet_no_op(
    db_session_factory: async_sessionmaker, fixtures_dir: Path, seed_group: SeedGroup, live_hub
) -> None:
    relay, _hub, operator_socket, _viewer = live_hub
    event_id = str(uuid.uuid4())  # an event below the alert threshold: it has no alert
    group = await seed_group(event_ids=[event_id])
    message = correlation_message(
        fixtures_dir, group_id=str(group.id), event_ids=[event_id], camera_ids=["cam02"]
    )

    await group_consumer(db_session_factory, relay).handle(message, None)  # type: ignore[arg-type]
    await asyncio.sleep(0.2)

    assert operator_socket.queue.empty()


async def test_the_group_consumer_survives_redis_being_down(
    db_session_factory: async_sessionmaker,
    fixtures_dir: Path,
    seed_alert: SeedAlert,
    seed_group: SeedGroup,
    unique_camera,
) -> None:
    """The push is a hint; the database is the record. A dead Redis must not fail the message
    (which would retry, then dead-letter it, for an effect that is already stored)."""
    from redis.exceptions import ConnectionError as RedisConnectionError  # noqa: PLC0415

    class DownRedis:
        async def publish(self, *_a: Any, **_k: Any) -> None:
            raise RedisConnectionError("down")

    alert = await seed_alert(camera=unique_camera)
    group = await seed_group(event_ids=[alert.event_id])
    message = correlation_message(
        fixtures_dir, group_id=str(group.id), event_ids=[alert.event_id], camera_ids=[unique_camera]
    )
    relay = RedisRelay(DownRedis(), ConnectionHub())  # type: ignore[arg-type]

    await group_consumer(db_session_factory, relay).handle(message, None)  # type: ignore[arg-type]

    assert await alert_group(db_session_factory, alert.id) == group.id


async def test_the_alert_count_per_event_is_one_whatever_the_consumers_do(
    db_session_factory: async_sessionmaker, fixtures_dir: Path, unique_camera
) -> None:
    events = [
        event_from_fixture(fixtures_dir, "intrusion", camera_id=unique_camera) for _ in range(4)
    ]
    consumer = event_consumer(db_session_factory)
    await asyncio.gather(*(consumer.handle(e, None) for e in events + events))  # type: ignore[arg-type]
    async with db_session_factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(Alert).where(Alert.camera_id == unique_camera)
        )
    assert count == 4
