"""Integration tests: camera CRUD (FR-CAM-01) and status merge (FR-CAM-02)
against real, migrated Postgres + Redis. Run via `make test-int`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis

pytestmark = pytest.mark.integration


def _unique_code(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _camera_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "code": _unique_code("cam"),
        "name": "Test Camera",
        "rtsp_url": "rtsp://mediamtx:8554/cam01",
        "site_id": "rvce-campus",
    }
    body.update(overrides)
    return body


def test_admin_can_create_list_get_update_and_delete_a_camera(
    client: TestClient, admin_access_token: str, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    headers = auth_headers(admin_access_token)

    created = client.post("/api/v1/cameras", json=_camera_body(), headers=headers)
    assert created.status_code == 201, created.text
    camera_id = created.json()["id"]
    assert created.json()["enabled"] is True

    listing = client.get("/api/v1/cameras", headers=headers)
    assert listing.status_code == 200
    assert any(c["id"] == camera_id for c in listing.json()["items"])

    fetched = client.get(f"/api/v1/cameras/{camera_id}", headers=headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["id"] == camera_id

    updated = client.patch(
        f"/api/v1/cameras/{camera_id}",
        json={"name": "Renamed Camera", "enabled": False},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Renamed Camera"
    assert updated.json()["enabled"] is False

    deleted = client.delete(f"/api/v1/cameras/{camera_id}", headers=headers)
    assert deleted.status_code == 204

    listing_after = client.get("/api/v1/cameras", headers=headers)
    assert not any(c["id"] == camera_id for c in listing_after.json()["items"])


def test_viewer_can_read_but_get_403_creating_a_camera(
    client: TestClient, admin_access_token: str, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    admin_headers = auth_headers(admin_access_token)
    email = f"viewer-{uuid.uuid4().hex[:8]}@example.com"
    created_user = client.post(
        "/api/v1/users",
        json={
            "email": email,
            "full_name": "Viewer",
            "password": "correct-horse-battery-1",
            "role": "viewer",
        },
        headers=admin_headers,
    )
    assert created_user.status_code == 201, created_user.text
    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "correct-horse-battery-1"}
    )
    viewer_headers = auth_headers(login.json()["access_token"])

    listing = client.get("/api/v1/cameras", headers=viewer_headers)
    assert listing.status_code == 200

    forbidden = client.post("/api/v1/cameras", json=_camera_body(), headers=viewer_headers)
    assert forbidden.status_code == 403


def test_creating_a_duplicate_code_returns_409(
    client: TestClient, admin_access_token: str, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    headers = auth_headers(admin_access_token)
    body = _camera_body()

    first = client.post("/api/v1/cameras", json=body, headers=headers)
    assert first.status_code == 201, first.text

    second = client.post("/api/v1/cameras", json=body, headers=headers)
    assert second.status_code == 409


def test_concurrent_duplicate_code_returns_409_not_500(
    client: TestClient,
    admin_access_token: str,
    auth_headers: Callable[[str], dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = auth_headers(admin_access_token)
    body = _camera_body()

    first = client.post("/api/v1/cameras", json=body, headers=headers)
    assert first.status_code == 201, first.text

    async def _report_no_existing_camera(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr("api.api.cameras.get_camera_by_code", _report_no_existing_camera)

    second = client.post("/api/v1/cameras", json=body, headers=headers)
    assert second.status_code == 409, second.text


def test_creating_a_camera_with_an_invalid_rtsp_url_returns_400(
    client: TestClient, admin_access_token: str, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    response = client.post(
        "/api/v1/cameras",
        json=_camera_body(rtsp_url="http://not-rtsp/cam01"),
        headers=auth_headers(admin_access_token),
    )
    assert response.status_code == 400


def test_updating_with_an_explicit_null_for_a_required_field_returns_400(
    client: TestClient, admin_access_token: str, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    headers = auth_headers(admin_access_token)
    created = client.post("/api/v1/cameras", json=_camera_body(), headers=headers)
    camera_id = created.json()["id"]

    response = client.patch(f"/api/v1/cameras/{camera_id}", json={"name": None}, headers=headers)
    assert response.status_code == 400


def test_updating_can_clear_a_nullable_field(
    client: TestClient, admin_access_token: str, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    headers = auth_headers(admin_access_token)
    created = client.post(
        "/api/v1/cameras",
        json=_camera_body(location_label="Old label", lat=12.9, lon=77.5),
        headers=headers,
    )
    camera_id = created.json()["id"]
    assert created.json()["location_label"] == "Old label"

    response = client.patch(
        f"/api/v1/cameras/{camera_id}", json={"location_label": None}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["location_label"] is None


def test_getting_an_unknown_camera_returns_404(
    client: TestClient, admin_access_token: str, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    response = client.get(
        f"/api/v1/cameras/{uuid.uuid4()}", headers=auth_headers(admin_access_token)
    )
    assert response.status_code == 404


async def test_cameras_status_merges_redis_heartbeats(
    client: TestClient,
    admin_access_token: str,
    auth_headers: Callable[[str], dict[str, str]],
    redis_client: Redis,
) -> None:
    headers = auth_headers(admin_access_token)

    online_code = _unique_code("online")
    reconnecting_code = _unique_code("reconnecting")
    offline_code = _unique_code("offline")

    for code in (online_code, reconnecting_code, offline_code):
        created = client.post("/api/v1/cameras", json=_camera_body(code=code), headers=headers)
        assert created.status_code == 201, created.text

    await redis_client.set(f"camera:status:{online_code}", "online", ex=15)
    await redis_client.set(f"camera:status:{reconnecting_code}", "reconnecting", ex=15)
    # offline_code: no heartbeat written at all — must read as "offline".

    response = client.get("/api/v1/cameras/status", headers=headers)
    assert response.status_code == 200, response.text
    status_by_code = {c["code"]: c["status"] for c in response.json()["cameras"]}

    assert status_by_code[online_code] == "online"
    assert status_by_code[reconnecting_code] == "reconnecting"
    assert status_by_code[offline_code] == "offline"
