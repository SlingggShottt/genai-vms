"""Integration tests: user CRUD (admin only, FR-AUTH-04). Run via
`make test-int`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from vms_db.models import AuditLog

pytestmark = pytest.mark.integration


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"


def test_listing_users_shows_a_just_created_user_on_the_first_page(
    client: TestClient, admin_access_token: str, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    """Regression test: listing used to order oldest-first with no cursor,
    so a newly created user became invisible on the default (first,
    unpaginated) page as soon as the table passed the page size — this
    surfaced when enough other integration tests had accumulated rows in
    the same shared test-session database. Newest-first fixes it structurally.
    """
    headers = auth_headers(admin_access_token)
    created = client.post(
        "/api/v1/users",
        json={
            "email": _unique_email("justcreated"),
            "full_name": "Just Created",
            "password": "correct-horse-battery-1",
            "role": "viewer",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text

    listing = client.get("/api/v1/users", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["items"][0]["id"] == created.json()["id"]


def test_admin_can_create_list_update_and_delete_a_user(
    client: TestClient, admin_access_token: str, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    headers = auth_headers(admin_access_token)
    email = _unique_email("operator")

    created = client.post(
        "/api/v1/users",
        json={
            "email": email,
            "full_name": "Op One",
            "password": "correct-horse-battery-1",
            "role": "operator",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]
    assert created.json()["role"] == "operator"

    listing = client.get("/api/v1/users", headers=headers)
    assert listing.status_code == 200
    assert any(u["id"] == user_id for u in listing.json()["items"])

    updated = client.patch(
        f"/api/v1/users/{user_id}", json={"role": "viewer", "is_active": False}, headers=headers
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["role"] == "viewer"
    assert updated.json()["is_active"] is False

    deleted = client.delete(f"/api/v1/users/{user_id}", headers=headers)
    assert deleted.status_code == 204

    listing_after = client.get("/api/v1/users", headers=headers)
    assert not any(u["id"] == user_id for u in listing_after.json()["items"])


def test_creating_a_duplicate_email_returns_409(
    client: TestClient,
    admin_access_token: str,
    admin_email: str,
    auth_headers: Callable[[str], dict[str, str]],
) -> None:
    response = client.post(
        "/api/v1/users",
        json={
            "email": admin_email,
            "full_name": "Dup",
            "password": "correct-horse-battery-1",
            "role": "viewer",
        },
        headers=auth_headers(admin_access_token),
    )
    assert response.status_code == 409


def test_updating_an_unknown_user_returns_404(
    client: TestClient, admin_access_token: str, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    response = client.patch(
        f"/api/v1/users/{uuid.uuid4()}",
        json={"is_active": False},
        headers=auth_headers(admin_access_token),
    )
    assert response.status_code == 404


def test_deleting_an_unknown_user_returns_404(
    client: TestClient, admin_access_token: str, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    response = client.delete(
        f"/api/v1/users/{uuid.uuid4()}", headers=auth_headers(admin_access_token)
    )
    assert response.status_code == 404


async def test_creating_a_user_writes_an_audit_log_entry(
    client: TestClient,
    admin_access_token: str,
    auth_headers: Callable[[str], dict[str, str]],
    migrated_postgres_dsn: str,
) -> None:
    """No audit-log read endpoint exists yet (out of P1-J2's surface), so
    verify the write directly against the DB rather than through the API.
    """
    response = client.post(
        "/api/v1/users",
        json={
            "email": _unique_email("audited"),
            "full_name": "Audited",
            "password": "correct-horse-battery-1",
            "role": "viewer",
        },
        headers=auth_headers(admin_access_token),
    )
    assert response.status_code == 201, response.text
    created_user_id = response.json()["id"]

    engine = create_async_engine(migrated_postgres_dsn)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                select(AuditLog).where(
                    AuditLog.action == "user.created", AuditLog.entity_id == created_user_id
                )
            )
            row = result.mappings().one_or_none()
    finally:
        await engine.dispose()

    assert row is not None
    assert row["entity_type"] == "user"


async def test_updating_with_an_explicit_null_is_not_applied_and_not_claimed_in_the_audit_log(
    client: TestClient,
    admin_access_token: str,
    auth_headers: Callable[[str], dict[str, str]],
    migrated_postgres_dsn: str,
) -> None:
    """Regression test: `update_user` treats an explicit `null` the same as
    "field not sent" (only `is not None` values are applied), but the audit
    `details` used to be built from `exclude_unset=True` alone, which
    includes explicit nulls — so the log used to claim a change that never
    happened.
    """
    headers = auth_headers(admin_access_token)
    created = client.post(
        "/api/v1/users",
        json={
            "email": _unique_email("nullcheck"),
            "full_name": "Original Name",
            "password": "correct-horse-battery-1",
            "role": "viewer",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    updated = client.patch(f"/api/v1/users/{user_id}", json={"full_name": None}, headers=headers)
    assert updated.status_code == 200, updated.text
    assert updated.json()["full_name"] == "Original Name"

    engine = create_async_engine(migrated_postgres_dsn)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                select(AuditLog).where(
                    AuditLog.action == "user.updated", AuditLog.entity_id == user_id
                )
            )
            row = result.mappings().one_or_none()
    finally:
        await engine.dispose()

    assert row is not None
    assert "full_name" not in row["details"]


async def test_concurrent_duplicate_email_returns_409_not_500(
    client: TestClient,
    admin_access_token: str,
    auth_headers: Callable[[str], dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulates the race window between the precheck and the insert: force
    the precheck to report "no existing user" even though one exists, so
    the endpoint falls through to the real insert and must translate the
    DB's own `IntegrityError` into 409 rather than a generic 500.
    """
    headers = auth_headers(admin_access_token)
    email = _unique_email("racer")

    first = client.post(
        "/api/v1/users",
        json={
            "email": email,
            "full_name": "Racer",
            "password": "correct-horse-battery-1",
            "role": "viewer",
        },
        headers=headers,
    )
    assert first.status_code == 201, first.text

    async def _report_no_existing_user(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr("api.api.users.get_user_by_email", _report_no_existing_user)

    second = client.post(
        "/api/v1/users",
        json={
            "email": email,
            "full_name": "Racer Two",
            "password": "correct-horse-battery-1",
            "role": "viewer",
        },
        headers=headers,
    )
    assert second.status_code == 409, second.text
