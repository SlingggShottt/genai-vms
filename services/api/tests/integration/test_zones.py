"""Integration tests: zone CRUD (FR-CAM-03) and `GET /internal/v1/zones`
against real, migrated Postgres. Run via `make test-int`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def _unique_code() -> str:
    return f"cam-{uuid.uuid4().hex[:8]}"


def _create_camera(client: TestClient, headers: dict[str, str]) -> dict[str, str]:
    code = _unique_code()
    resp = client.post(
        "/api/v1/cameras",
        json={
            "code": code,
            "name": "Test Camera",
            "rtsp_url": "rtsp://mediamtx:8554/" + code,
            "site_id": "rvce-campus",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _zone_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "name": "Restricted yard",
        "zone_type": "restricted",
        "polygon": [[0.1, 0.4], [0.6, 0.35], [0.65, 0.9], [0.05, 0.85]],
    }
    body.update(overrides)
    return body


def test_admin_can_create_list_update_and_delete_a_zone(
    client: TestClient, admin_access_token: str, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    headers = auth_headers(admin_access_token)
    camera = _create_camera(client, headers)

    created = client.post(
        f"/api/v1/cameras/{camera['id']}/zones", json=_zone_body(), headers=headers
    )
    assert created.status_code == 201, created.text
    zone = created.json()
    assert zone["camera_id"] == camera["id"]
    assert zone["zone_type"] == "restricted"
    assert zone["schedule"] is None

    listing = client.get(f"/api/v1/cameras/{camera['id']}/zones", headers=headers)
    assert listing.status_code == 200, listing.text
    assert [z["id"] for z in listing.json()["items"]] == [zone["id"]]

    updated = client.patch(
        f"/api/v1/zones/{zone['id']}",
        json={
            "name": "Renamed zone",
            "schedule": {"start_time": "20:00", "end_time": "06:00", "days": ["mon", "tue"]},
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Renamed zone"
    assert updated.json()["schedule"]["start_time"] == "20:00"

    cleared = client.patch(f"/api/v1/zones/{zone['id']}", json={"schedule": None}, headers=headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["schedule"] is None

    deleted = client.delete(f"/api/v1/zones/{zone['id']}", headers=headers)
    assert deleted.status_code == 204

    after_delete = client.get(f"/api/v1/cameras/{camera['id']}/zones", headers=headers)
    assert after_delete.json()["items"] == []


def test_create_zone_rejects_an_invalid_polygon(
    client: TestClient, admin_access_token: str, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    headers = auth_headers(admin_access_token)
    camera = _create_camera(client, headers)

    resp = client.post(
        f"/api/v1/cameras/{camera['id']}/zones",
        json=_zone_body(polygon=[[0.1, 0.1], [0.5, 0.5]]),  # only 2 points
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_create_zone_404s_for_an_unknown_camera(
    client: TestClient, admin_access_token: str, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    headers = auth_headers(admin_access_token)
    resp = client.post(f"/api/v1/cameras/{uuid.uuid4()}/zones", json=_zone_body(), headers=headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_update_zone_rejects_null_for_a_non_nullable_field(
    client: TestClient, admin_access_token: str, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    headers = auth_headers(admin_access_token)
    camera = _create_camera(client, headers)
    created = client.post(
        f"/api/v1/cameras/{camera['id']}/zones", json=_zone_body(), headers=headers
    )
    zone_id = created.json()["id"]

    resp = client.patch(f"/api/v1/zones/{zone_id}", json={"name": None}, headers=headers)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_internal_zones_endpoint_uses_camera_code_not_id(
    client: TestClient,
    admin_access_token: str,
    auth_headers: Callable[[str], dict[str, str]],
    service_token: str,
) -> None:
    headers = auth_headers(admin_access_token)
    camera = _create_camera(client, headers)
    client.post(f"/api/v1/cameras/{camera['id']}/zones", json=_zone_body(), headers=headers)

    resp = client.get(
        "/api/v1/internal/v1/zones", headers={"Authorization": f"Bearer {service_token}"}
    )
    assert resp.status_code == 200, resp.text
    matching = [z for z in resp.json()["zones"] if z["camera_id"] == camera["code"]]
    assert len(matching) == 1
    assert matching[0]["zone_type"] == "restricted"


def test_internal_zones_endpoint_rejects_a_user_token(
    client: TestClient, admin_access_token: str, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    resp = client.get("/api/v1/internal/v1/zones", headers=auth_headers(admin_access_token))
    assert resp.status_code == 401
