"""`GET /events` and `GET /events/{id}` over a real Postgres and S3 double (design §9): filters,
newest-first paging that survives ties, the rejected-hiding rule, the group and alert links, and
keyframes presigned per request. Run via `make test-int`."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from vms_db.models import Event

pytestmark = pytest.mark.integration

Headers = Callable[[str], dict[str, str]]
SeedEvent = Callable[..., Awaitable[Event]]

NOON = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def viewer(make_user: Callable[[str], dict[str, str]]) -> dict[str, str]:
    return make_user("viewer")


def get(client: TestClient, headers: dict[str, str], path: str, **params: Any):
    return client.get(f"/api/v1{path}", headers=headers, params=params)


def ids(body: dict) -> list[str]:
    return [e["id"] for e in body["items"]]


async def test_a_viewer_lists_events_newest_first_with_the_gates_reasoning(
    client: TestClient, viewer: dict, auth_headers: Headers, seed_event: SeedEvent, unique_camera
) -> None:
    older = await seed_event(camera=unique_camera, start_ts=NOON)
    newer = await seed_event(
        camera=unique_camera, event_type="loitering", severity="low", start_ts=NOON + timedelta(1)
    )

    body = get(client, auth_headers(viewer["token"]), "/events", camera=unique_camera).json()

    assert ids(body) == [str(newer.id), str(older.id)] and body["next_cursor"] is None
    first = body["items"][0]
    assert first["camera_code"] == unique_camera and first["camera_id"] is None
    assert first["event_type"] == "loitering" and first["severity"] == "low"
    assert first["status"] == "verified" and first["zone_name"] == "Back fence"
    assert first["verification"]["verdict"] == "yes" and first["verification"]["caption"]
    assert first["verification"]["model"] == "qwen2.5vl:3b"
    assert first["keyframe_count"] == 2 and first["keyframe_urls"] == []  # urls: detail only
    assert first["group"] is None and first["alert_id"] is None


async def test_filters_narrow_the_list_and_combine(
    client: TestClient, viewer: dict, auth_headers: Headers, seed_event: SeedEvent, unique_camera
) -> None:
    low = await seed_event(camera=unique_camera, severity="low", start_ts=NOON)
    high = await seed_event(camera=unique_camera, severity="high", start_ts=NOON + timedelta(1))
    loiter = await seed_event(
        camera=unique_camera, event_type="loitering", severity="high", start_ts=NOON + timedelta(2)
    )
    headers = auth_headers(viewer["token"])

    def listed(**params: Any) -> list[str]:
        return ids(get(client, headers, "/events", camera=unique_camera, **params).json())

    assert listed(severity=["high", "critical"]) == [str(loiter.id), str(high.id)]
    assert listed(type="loitering") == [str(loiter.id)]
    assert listed(type=["loitering", "intrusion"], severity="low") == [str(low.id)]
    assert listed(start=(NOON + timedelta(1)).isoformat()) == [str(loiter.id), str(high.id)]
    # `end` is exclusive, like `start` is inclusive
    assert listed(end=(NOON + timedelta(1)).isoformat()) == [str(low.id)]
    assert listed(status="skipped") == []


async def test_rejected_events_are_hidden_unless_asked_for(
    client: TestClient, viewer: dict, auth_headers: Headers, seed_event: SeedEvent, unique_camera
) -> None:
    kept = await seed_event(camera=unique_camera, status="verified", start_ts=NOON)
    unasked = await seed_event(camera=unique_camera, status="skipped", start_ts=NOON)
    no = await seed_event(camera=unique_camera, status="rejected", start_ts=NOON)
    headers = auth_headers(viewer["token"])

    default = ids(get(client, headers, "/events", camera=unique_camera).json())
    assert set(default) == {str(kept.id), str(unasked.id)}
    only_rejected = ids(
        get(client, headers, "/events", camera=unique_camera, status="rejected").json()
    )
    assert only_rejected == [str(no.id)]
    assert get(client, headers, f"/events/{no.id}").json()["status"] == "rejected"  # readable by id


async def test_paging_walks_every_event_once_even_when_they_share_a_start(
    client: TestClient, viewer: dict, auth_headers: Headers, seed_event: SeedEvent, unique_camera
) -> None:
    seeded = [
        await seed_event(camera=unique_camera, start_ts=NOON + timedelta(seconds=i // 3))
        for i in range(7)  # groups of three share a start, so a page can end inside a tie
    ]
    headers = auth_headers(viewer["token"])

    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"camera": unique_camera, "limit": 2, **({"cursor": cursor} if cursor else {})}
        body = get(client, headers, "/events", **params).json()
        assert len(body["items"]) <= 2
        seen += ids(body)
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert len(seen) == len(set(seen)) == 7 and set(seen) == {str(e.id) for e in seeded}
    starts = [
        datetime.fromisoformat(e["start_ts"])
        for e in get(client, headers, "/events", camera=unique_camera, limit=200).json()["items"]
    ]
    assert starts == sorted(starts, reverse=True)


async def test_the_detail_presigns_keyframes_and_links_the_group_and_alert(
    client: TestClient,
    viewer: dict,
    auth_headers: Headers,
    seed_event: SeedEvent,
    seed_alert,
    seed_group,
    unique_camera,
) -> None:
    event = await seed_event(camera=unique_camera, start_ts=NOON, keyframes=2)
    alert = await seed_alert(camera=unique_camera, event_id=str(event.id))
    group = await seed_group(event_ids=[str(event.id)], cameras=(unique_camera,))
    headers = auth_headers(viewer["token"])

    detail = get(client, headers, f"/events/{event.id}").json()

    assert len(detail["keyframe_urls"]) == 2 and detail["keyframe_count"] == 2
    for url in detail["keyframe_urls"]:
        assert url.startswith("http") and "X-Amz-Expires=900" in url  # 15 minutes (NFR-SEC-02)
    assert detail["group"]["id"] == str(group.id) and detail["alert_id"] == str(alert.id)
    listed = get(client, headers, "/events", camera=unique_camera).json()["items"][0]
    assert listed["group"]["id"] == str(group.id) and listed["alert_id"] == str(alert.id)


async def test_an_event_in_a_merged_group_reports_the_survivor(
    client: TestClient,
    viewer: dict,
    auth_headers: Headers,
    seed_event: SeedEvent,
    seed_group,
    unique_camera,
) -> None:
    event = await seed_event(camera=unique_camera, start_ts=NOON)
    survivor = await seed_group(event_ids=[str(uuid.uuid4())], cameras=(unique_camera,))
    await seed_group(
        event_ids=[str(event.id)],
        status="merged",
        merged_into=survivor.id,
        cameras=(unique_camera,),
    )

    detail = get(client, auth_headers(viewer["token"]), f"/events/{event.id}").json()

    assert detail["group"]["id"] == str(survivor.id)


async def test_bad_requests_get_the_error_envelope(
    client: TestClient, viewer: dict, auth_headers: Headers
) -> None:
    headers = auth_headers(viewer["token"])

    assert get(client, headers, "/events", cursor="nonsense").status_code == 400
    assert get(client, headers, "/events", limit=0).status_code == 400
    assert get(client, headers, "/events", severity="catastrophic").status_code == 400
    backwards = get(
        client, headers, "/events", start=NOON.isoformat(), end=(NOON - timedelta(1)).isoformat()
    )
    assert backwards.status_code == 400 and backwards.json()["error"]["code"] == "VALIDATION_ERROR"
    assert get(client, headers, "/events/not-a-uuid").status_code == 400
    missing = get(client, headers, f"/events/{uuid.uuid4()}")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "NOT_FOUND"
