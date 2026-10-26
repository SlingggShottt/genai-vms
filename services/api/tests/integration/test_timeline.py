"""`GET /timeline` over a real Postgres (P6-J4): the lanes' data for a period, and which events a
correlation group links. Run via `make test-int`."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from vms_db.models import CorrelationGroup, Event

pytestmark = pytest.mark.integration

Headers = Callable[[str], dict[str, str]]
SeedEvent = Callable[..., Awaitable[Event]]
SeedGroup = Callable[..., Awaitable[CorrelationGroup]]

NOON = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def viewer(make_user: Callable[[str], dict[str, str]]) -> dict[str, str]:
    return make_user("viewer")


def timeline(client: TestClient, headers: dict[str, str], **params: Any):
    return client.get("/api/v1/timeline", headers=headers, params=params)


async def test_events_come_back_per_camera_and_a_group_names_the_events_it_links(
    client: TestClient,
    viewer: dict,
    auth_headers: Headers,
    seed_event: SeedEvent,
    seed_group: SeedGroup,
    unique_camera,
) -> None:
    a = await seed_event(camera=f"{unique_camera}-a", start_ts=NOON)
    b = await seed_event(camera=f"{unique_camera}-b", start_ts=NOON + timedelta(seconds=30))
    alone = await seed_event(camera=f"{unique_camera}-a", start_ts=NOON + timedelta(minutes=10))
    group = await seed_group(
        event_ids=[str(a.id), str(b.id)],
        cameras=(f"{unique_camera}-a", f"{unique_camera}-b"),
        start_ts=NOON,
    )

    body = timeline(
        client,
        auth_headers(viewer["token"]),
        start=(NOON - timedelta(minutes=1)).isoformat(),
        end=(NOON + timedelta(minutes=30)).isoformat(),
        cameras=[f"{unique_camera}-a", f"{unique_camera}-b"],
    ).json()

    assert {e["id"] for e in body["events"]} == {str(a.id), str(b.id), str(alone.id)}
    linked = next(g for g in body["groups"] if g["id"] == str(group.id))
    assert set(linked["event_ids"]) == {str(a.id), str(b.id)} and linked["events"] == 2
    assert set(linked["camera_ids"]) == {f"{unique_camera}-a", f"{unique_camera}-b"}


async def test_a_group_of_one_camera_is_not_a_link_and_a_rejected_event_is_not_drawn(
    client: TestClient,
    viewer: dict,
    auth_headers: Headers,
    seed_event: SeedEvent,
    seed_group: SeedGroup,
    unique_camera,
) -> None:
    kept = await seed_event(camera=unique_camera, start_ts=NOON)
    await seed_event(camera=unique_camera, start_ts=NOON, status="rejected")
    await seed_group(event_ids=[str(kept.id)], cameras=(unique_camera,))

    body = timeline(
        client,
        auth_headers(viewer["token"]),
        start=(NOON - timedelta(minutes=1)).isoformat(),
        end=(NOON + timedelta(minutes=1)).isoformat(),
        cameras=[unique_camera],
    ).json()

    assert [e["id"] for e in body["events"]] == [str(kept.id)]
    assert not [g for g in body["groups"] if str(kept.id) in g["event_ids"]]


async def test_a_period_must_run_forwards_and_not_past_a_week(
    client: TestClient, viewer: dict, auth_headers: Headers
) -> None:
    headers = auth_headers(viewer["token"])
    backwards = timeline(
        client, headers, start=NOON.isoformat(), end=(NOON - timedelta(1)).isoformat()
    )
    too_long = timeline(
        client, headers, start=NOON.isoformat(), end=(NOON + timedelta(days=8)).isoformat()
    )
    assert backwards.status_code == 400 and too_long.status_code == 400
