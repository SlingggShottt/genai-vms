"""Integration tests: `GET /internal/v1/cameras` (design_architecture.md
§16 "Camera internal API"), service-token protected — never a user JWT.
Run via `make test-int`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def _unique_code(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_requires_a_service_token(client: TestClient) -> None:
    response = client.get("/api/v1/internal/v1/cameras")
    assert response.status_code == 401


def test_rejects_a_wrong_service_token(client: TestClient) -> None:
    response = client.get(
        "/api/v1/internal/v1/cameras", headers={"Authorization": "Bearer wrong-token"}
    )
    assert response.status_code == 401


def test_a_user_jwt_is_not_accepted_in_place_of_a_service_token(
    client: TestClient, admin_access_token: str, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    response = client.get("/api/v1/internal/v1/cameras", headers=auth_headers(admin_access_token))
    assert response.status_code == 401


def test_returns_every_camera_including_disabled_ones(
    client: TestClient,
    admin_access_token: str,
    service_token: str,
    auth_headers: Callable[[str], dict[str, str]],
) -> None:
    admin_headers = auth_headers(admin_access_token)
    enabled_code = _unique_code("enabled")
    disabled_code = _unique_code("disabled")

    enabled = client.post(
        "/api/v1/cameras",
        json={
            "code": enabled_code,
            "name": "Enabled Cam",
            "rtsp_url": "rtsp://mediamtx:8554/camE",
            "site_id": "rvce-campus",
            "enabled": True,
        },
        headers=admin_headers,
    )
    disabled = client.post(
        "/api/v1/cameras",
        json={
            "code": disabled_code,
            "name": "Disabled Cam",
            "rtsp_url": "rtsp://mediamtx:8554/camD",
            "site_id": "rvce-campus",
            "enabled": False,
        },
        headers=admin_headers,
    )
    assert enabled.status_code == 201, enabled.text
    assert disabled.status_code == 201, disabled.text

    response = client.get(
        "/api/v1/internal/v1/cameras", headers={"Authorization": f"Bearer {service_token}"}
    )
    assert response.status_code == 200, response.text

    by_code = {c["code"]: c for c in response.json()["cameras"]}
    assert enabled_code in by_code
    assert disabled_code in by_code
    # The internal API doesn't filter by enabled — ingestion's own
    # resolve_cameras() does that (design_architecture.md §16).
    assert by_code[disabled_code]["enabled"] is False
