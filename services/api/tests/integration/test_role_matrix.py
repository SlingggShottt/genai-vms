"""Role x endpoint test matrix (P1-J2 AC). `ROUTER_TABLE` below mirrors the
`require_role(...)` / `Depends(get_current_user)` declarations each router
in services/api/src/api/api/ actually carries — it's the single source this
matrix is generated from. If a router's auth requirement changes, update
this table in the same commit. Run via `make test-int`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

ROLES = ("admin", "operator", "viewer")

# (method, path template, roles allowed to call it — None means "any
# authenticated role", matching every router's actual dependency today.
ROUTER_TABLE: list[tuple[str, str, frozenset[str] | None]] = [
    ("GET", "/api/v1/users", frozenset({"admin"})),
    ("POST", "/api/v1/users", frozenset({"admin"})),
    ("PATCH", "/api/v1/users/{target_id}", frozenset({"admin"})),
    ("DELETE", "/api/v1/users/{target_id}", frozenset({"admin"})),
    ("GET", "/api/v1/auth/me", None),
]


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"


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


@pytest.fixture
def role_tokens(
    client: TestClient, admin_access_token: str, auth_headers: Callable[[str], dict[str, str]]
) -> dict[str, str]:
    admin_headers = auth_headers(admin_access_token)
    _, operator_token = _create_user(client, admin_headers, "operator")
    _, viewer_token = _create_user(client, admin_headers, "viewer")
    return {"admin": admin_access_token, "operator": operator_token, "viewer": viewer_token}


def _call(client: TestClient, method: str, path: str, headers: dict[str, str] | None) -> int:
    # Only two request shapes exist in ROUTER_TABLE today: POST /users needs
    # a full create body, PATCH /users/{id} needs a partial update body.
    body: dict[str, object] | None = None
    if method == "POST":
        body = {
            "email": _unique_email("target"),
            "full_name": "Target",
            "password": "correct-horse-battery-1",
            "role": "viewer",
        }
    elif method == "PATCH":
        body = {"full_name": "Renamed"}
    return client.request(method, path, json=body, headers=headers).status_code


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
    target_id, _ = _create_user(client, auth_headers(admin_access_token), "viewer")
    resolved_path = path.format(target_id=target_id)

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
    resolved_path = path.format(target_id=str(uuid.uuid4()))
    status_code = _call(client, method, resolved_path, None)
    assert status_code == 401
