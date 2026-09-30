"""Role x endpoint test matrix (P1-J2 AC). `ROUTER_TABLE` below mirrors the
`require_role(...)` / `Depends(get_current_user)` declarations each router
in services/api/src/api/api/ actually carries — it's the single source this
matrix is generated from. If a router's auth requirement changes (or a new
router's endpoints are added), update this table in the same commit. Run
via `make test-int`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

_WINDOW_START = datetime(2026, 1, 1, tzinfo=UTC)
_WINDOW_END = _WINDOW_START + timedelta(seconds=30)

ROLES = ("admin", "operator", "viewer")

# (method, path template, roles allowed to call it — None means "any
# authenticated role", matching every router's actual dependency today.
# `{target_id}` is resolved per-call to a freshly created resource of the
# right kind (a user id for /users/..., a camera id for /cameras/...) — see
# `_target_id_for`. /internal/* isn't here: it's service-token gated, not
# role gated, and covered by tests/integration/test_internal.py instead.
ROUTER_TABLE: list[tuple[str, str, frozenset[str] | None]] = [
    ("GET", "/api/v1/users", frozenset({"admin"})),
    ("POST", "/api/v1/users", frozenset({"admin"})),
    ("PATCH", "/api/v1/users/{target_id}", frozenset({"admin"})),
    ("DELETE", "/api/v1/users/{target_id}", frozenset({"admin"})),
    ("GET", "/api/v1/auth/me", None),
    ("GET", "/api/v1/cameras", None),
    ("POST", "/api/v1/cameras", frozenset({"admin"})),
    ("GET", "/api/v1/cameras/status", None),
    ("GET", "/api/v1/cameras/{target_id}", None),
    ("PATCH", "/api/v1/cameras/{target_id}", frozenset({"admin"})),
    ("DELETE", "/api/v1/cameras/{target_id}", frozenset({"admin"})),
    ("GET", "/api/v1/recordings/{camera_id}/segments", None),
    ("GET", "/api/v1/recordings/{camera_id}/playlist.m3u8", None),
    ("GET", "/api/v1/recordings/{camera_id}/density", None),
    ("GET", "/api/v1/twin/{camera_id}/frames", None),
    ("GET", "/api/v1/cameras/{target_id}/zones", None),
    ("POST", "/api/v1/cameras/{target_id}/zones", frozenset({"admin"})),
    ("PATCH", "/api/v1/zones/{target_id}", frozenset({"admin"})),
    ("DELETE", "/api/v1/zones/{target_id}", frozenset({"admin"})),
]


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"


def _unique_code(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _create_user(client: TestClient, admin_headers: dict[str, str], role: str) -> tuple[str, str]:
    """Create a user with `role` as admin; returns (user_id, that user's access_token)."""
    email = _unique_email(role)
    password = "correct-horse-battery-1"  # noqa: S105 — fixture value
    created = client.post(
        "/api/v1/users",
        json={"email": email, "full_name": role.title(), "password": password, "role": role},
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return created.json()["id"], login.json()["access_token"]


def _create_camera(client: TestClient, admin_headers: dict[str, str]) -> str:
    """Create a camera as admin; returns its id."""
    created = client.post(
        "/api/v1/cameras",
        json={
            "code": _unique_code("cam"),
            "name": "Matrix Test Camera",
            "rtsp_url": "rtsp://mediamtx:8554/matrix",
            "site_id": "rvce-campus",
        },
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _create_camera_code(client: TestClient, admin_headers: dict[str, str]) -> str:
    """Create a camera as admin; returns its `code` — recordings/twin
    endpoints key on the camera's code, not its id (media.segments and
    vision.minute_counts denormalize `camera.code` from Kafka messages;
    see services/indexer/README.md).
    """
    code = _unique_code("cam")
    created = client.post(
        "/api/v1/cameras",
        json={
            "code": code,
            "name": "Matrix Test Camera",
            "rtsp_url": "rtsp://mediamtx:8554/matrix",
            "site_id": "rvce-campus",
        },
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    return code


def _create_zone_id(client: TestClient, admin_headers: dict[str, str]) -> str:
    """Create a camera, then a zone under it as admin; returns the zone's id."""
    camera_id = _create_camera(client, admin_headers)
    created = client.post(
        f"/api/v1/cameras/{camera_id}/zones",
        json={
            "name": "Matrix Test Zone",
            "zone_type": "restricted",
            "polygon": [[0.1, 0.1], [0.5, 0.2], [0.3, 0.6]],
        },
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _path_kwargs_for(
    path: str, client: TestClient, admin_headers: dict[str, str]
) -> dict[str, str]:
    kwargs: dict[str, str] = {}
    if "{target_id}" in path:
        if "/cameras/" in path:
            kwargs["target_id"] = _create_camera(client, admin_headers)
        elif "/zones/" in path:
            kwargs["target_id"] = _create_zone_id(client, admin_headers)
        else:
            user_id, _ = _create_user(client, admin_headers, "viewer")
            kwargs["target_id"] = user_id
    if "{camera_id}" in path:
        kwargs["camera_id"] = _create_camera_code(client, admin_headers)
    return kwargs


@pytest.fixture
def role_tokens(
    client: TestClient, admin_access_token: str, auth_headers: Callable[[str], dict[str, str]]
) -> dict[str, str]:
    admin_headers = auth_headers(admin_access_token)
    _, operator_token = _create_user(client, admin_headers, "operator")
    _, viewer_token = _create_user(client, admin_headers, "viewer")
    return {"admin": admin_access_token, "operator": operator_token, "viewer": viewer_token}


def _body_for(method: str, path: str) -> dict[str, object] | None:
    if method == "POST" and path == "/api/v1/users":
        return {
            "email": _unique_email("target"),
            "full_name": "Target",
            "password": "correct-horse-battery-1",
            "role": "viewer",
        }
    if method == "POST" and path == "/api/v1/cameras":
        return {
            "code": _unique_code("target"),
            "name": "Target Camera",
            "rtsp_url": "rtsp://mediamtx:8554/target",
            "site_id": "rvce-campus",
        }
    if method == "POST" and "/cameras/" in path and path.endswith("/zones"):
        return {
            "name": "Target Zone",
            "zone_type": "restricted",
            "polygon": [[0.1, 0.1], [0.5, 0.2], [0.3, 0.6]],
        }
    if method == "PATCH" and "/users/" in path:
        return {"full_name": "Renamed"}
    if method == "PATCH" and "/cameras/" in path:
        return {"name": "Renamed"}
    if method == "PATCH" and "/zones/" in path:
        return {"name": "Renamed Zone"}
    return None


def _params_for(path: str) -> dict[str, str] | None:
    if "/recordings/" in path or "/twin/" in path:
        return {"start": _WINDOW_START.isoformat(), "end": _WINDOW_END.isoformat()}
    return None


def _call(client: TestClient, method: str, path: str, headers: dict[str, str] | None) -> int:
    body = _body_for(method, path)
    params = _params_for(path)
    return client.request(method, path, json=body, params=params, headers=headers).status_code


@pytest.mark.parametrize("method,path,allowed_roles", ROUTER_TABLE)
@pytest.mark.parametrize("role", ROLES)
def test_router_table_role_matrix(
    client: TestClient,
    admin_access_token: str,
    role_tokens: dict[str, str],
    auth_headers: Callable[[str], dict[str, str]],
    role: str,
    method: str,
    path: str,
    allowed_roles: frozenset[str] | None,
) -> None:
    admin_headers = auth_headers(admin_access_token)
    resolved_path = path.format(**_path_kwargs_for(path, client, admin_headers))

    status_code = _call(client, method, resolved_path, auth_headers(role_tokens[role]))

    if allowed_roles is None or role in allowed_roles:
        assert status_code < 400, (
            f"{method} {resolved_path} as {role}: expected success, got {status_code}"
        )
    else:
        assert status_code == 403, (
            f"{method} {resolved_path} as {role}: expected 403, got {status_code}"
        )


@pytest.mark.parametrize("method,path,allowed_roles", ROUTER_TABLE)
def test_router_table_rejects_unauthenticated(
    client: TestClient, method: str, path: str, allowed_roles: frozenset[str] | None
) -> None:
    # Unauthenticated requests 401 before any resource lookup, so the
    # placeholder values themselves don't need to resolve to anything real.
    resolved_path = path.format(target_id=str(uuid.uuid4()), camera_id="does-not-matter")
    status_code = _call(client, method, resolved_path, None)
    assert status_code == 401
