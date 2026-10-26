"""`POST /search/image/crop` (P4-J1) over a real Postgres: how the browser names a frame becomes
the request the retrieval service understands, and who may ask. The retrieval service itself is a
fake here (`_forward` is replaced); its half is covered in services/retrieval. `make test-int`."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from api.api import search as search_module
from fastapi.testclient import TestClient
from vms_db.models import Event

pytestmark = pytest.mark.integration

Headers = Callable[[str], dict[str, str]]
SeedEvent = Callable[..., Awaitable[Event]]
BOX = [0.2, 0.2, 0.6, 0.7]


@pytest.fixture
def viewer(make_user: Callable[[str], dict[str, str]]) -> dict[str, str]:
    return make_user("viewer")


@pytest.fixture
def forwarded(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_forward(request, user, path, **kwargs):  # noqa: ANN001, ANN202, ANN003
        calls.append({"path": path, "json": kwargs["json"], "user": str(user.id)})
        return {"search_id": "s", "results": []}

    monkeypatch.setattr(search_module, "_forward", fake_forward)
    return calls


def crop(client: TestClient, headers: dict[str, str], **body: Any):
    return client.post("/api/v1/search/image/crop", headers=headers, json={"bbox": BOX, **body})


async def test_an_events_keyframe_is_named_by_the_server_not_the_browser(
    client: TestClient,
    viewer: dict,
    auth_headers: Headers,
    seed_event: SeedEvent,
    forwarded: list,
    unique_camera,
) -> None:
    event = await seed_event(camera=unique_camera, keyframes=3)

    response = crop(
        client,
        auth_headers(viewer["token"]),
        event_id=str(event.id),
        keyframe_index=1,
        cameras=["cam02"],
        top_k=5,
    )

    assert response.status_code == 200 and response.json()["results"] == []
    (call,) = forwarded
    assert call["path"] == "/search/crop" and call["user"] == viewer["id"]
    assert call["json"]["keyframe_uri"] == event.keyframe_uris[1]
    assert call["json"]["bbox"] == BOX and call["json"]["top_k"] == 5
    assert call["json"]["filters"]["cameras"] == ["cam02"]
    assert call["json"]["search_id"] is None and call["json"]["camera_id"] is None


async def test_an_event_without_that_keyframe_or_without_keyframes_is_not_found(
    client: TestClient,
    viewer: dict,
    auth_headers: Headers,
    seed_event: SeedEvent,
    forwarded: list,
    unique_camera,
) -> None:
    event = await seed_event(camera=unique_camera, keyframes=1)
    headers = auth_headers(viewer["token"])

    assert crop(client, headers, event_id=str(event.id), keyframe_index=1).status_code == 404
    assert crop(client, headers, event_id=str(uuid.uuid4())).status_code == 404
    assert forwarded == []


def test_a_result_of_a_recent_search_and_a_moment_on_a_camera_are_passed_on_as_they_are(
    client: TestClient, viewer: dict, auth_headers: Headers, forwarded: list
) -> None:
    headers = auth_headers(viewer["token"])

    assert crop(client, headers, search_id="s1", result_id="r1").status_code == 200
    assert (
        crop(client, headers, camera_id="cam02", at="2026-10-25T09:30:00+00:00").status_code == 200
    )

    assert forwarded[0]["json"]["search_id"] == "s1" and forwarded[0]["json"]["result_id"] == "r1"
    assert forwarded[1]["json"]["camera_id"] == "cam02"
    assert forwarded[1]["json"]["at"].startswith("2026-10-25T09:30:00")


@pytest.mark.parametrize(
    "body",
    [
        {},  # no frame named
        {"search_id": "s1"},  # half of a pair
        {"camera_id": "cam02"},
        {"event_id": "not-a-uuid"},
        {"event_id": str(uuid.uuid4()), "search_id": "s1", "result_id": "r1"},  # two ways
        {"search_id": "s1", "result_id": "r1", "bbox": [0.5, 0.5, 0.5, 0.5]},  # no area
        {"search_id": "s1", "result_id": "r1", "bbox": [0.1, 0.1, 1.5, 0.5]},  # off the frame
    ],
)
def test_a_request_that_does_not_name_one_frame_and_a_real_box_is_a_400(
    client: TestClient, viewer: dict, auth_headers: Headers, forwarded: list, body: dict
) -> None:
    response = client.post(
        "/api/v1/search/image/crop",
        headers=auth_headers(viewer["token"]),
        json={"bbox": BOX, **body},
    )
    assert response.status_code == 400 and response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert forwarded == []


def test_a_login_is_needed(client: TestClient, forwarded: list) -> None:
    response = client.post(
        "/api/v1/search/image/crop", json={"bbox": BOX, "search_id": "s", "result_id": "r"}
    )
    assert response.status_code == 401 and forwarded == []


def test_the_frame_lookup_presigns_the_frame_the_retrieval_service_found(
    client: TestClient, viewer: dict, auth_headers: Headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    async def fake_forward(request, user, path, *, method="POST", **kwargs):  # noqa: ANN001, ANN202, ANN003
        seen.update(path=path, method=method, params=kwargs["params"])
        return {
            "keyframe_uri": "s3://vms-keyframes/cam02/near.jpg",
            "at": "2026-10-25T09:30:19+00:00",
        }

    monkeypatch.setattr(search_module, "_forward", fake_forward)

    response = client.get(
        "/api/v1/search/frame",
        headers=auth_headers(viewer["token"]),
        params={"camera_id": "cam02", "at": "2026-10-25T09:30:15+00:00"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["at"] == "2026-10-25T09:30:19+00:00" and body["camera_id"] == "cam02"
    assert body["url"].startswith("http") and "X-Amz-Expires=900" in body["url"]
    assert "s3://" not in str(body)  # a storage uri never reaches the browser
    assert seen["path"] == "/search/frame" and seen["method"] == "GET"
    assert seen["params"]["camera_id"] == "cam02"


def test_the_frame_lookup_needs_a_login_and_a_zoned_time(
    client: TestClient, viewer: dict, auth_headers: Headers
) -> None:
    params = {"camera_id": "cam02", "at": "2026-10-25T09:30:15+00:00"}
    assert client.get("/api/v1/search/frame", params=params).status_code == 401
    naive = client.get(
        "/api/v1/search/frame",
        headers=auth_headers(viewer["token"]),
        params={"camera_id": "cam02", "at": "2026-10-25T09:30:15"},
    )
    assert naive.status_code == 400
