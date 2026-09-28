"""Integration tests: login/refresh/logout/me against a real, migrated
Postgres (P1-J2 AC: login issues access+refresh JWTs, refresh rotation,
logout revokes; FR-AUTH-01). Run via `make test-int`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from vms_db.models import AuditLog

pytestmark = pytest.mark.integration


def test_login_with_valid_credentials_returns_token_pair(
    client: TestClient, admin_email: str, admin_password: str
) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": admin_email, "password": admin_password}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"  # noqa: S105 — OAuth2 scheme name, not a secret
    assert body["expires_in"] == 15 * 60
    assert body["access_token"]
    assert body["refresh_token"]


def test_login_with_wrong_password_returns_401(client: TestClient, admin_email: str) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": admin_email, "password": "not-the-password"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_with_unknown_email_returns_401(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "whatever123"},
    )
    assert response.status_code == 401


async def test_failed_login_writes_an_audit_log_entry(
    client: TestClient, admin_email: str, migrated_postgres_dsn: str
) -> None:
    """Regression test for a bug the P1-J2 review caught: `write_audit_log`
    used to run on the request's own session, which `session_scope` rolls
    back once `login` raises `APIError` right after — the "user.login_failed"
    row never reached the DB. `write_audit_log` now commits independently.
    """
    response = client.post(
        "/api/v1/auth/login", json={"email": admin_email, "password": "not-the-password"}
    )
    assert response.status_code == 401

    # Other tests in this module also trigger "user.login_failed" against
    # the same shared container — take the most recent match, which is this
    # attempt's, rather than assuming there's exactly one in the whole table.
    engine = create_async_engine(migrated_postgres_dsn)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                select(AuditLog)
                .where(AuditLog.action == "user.login_failed")
                .order_by(AuditLog.created_at.desc())
                .limit(1)
            )
            row = result.mappings().one_or_none()
    finally:
        await engine.dispose()

    assert row is not None
    assert row["details"] == {"email": admin_email}
    # entity_id must be the admin's real UUID here (the account exists — only
    # the password was wrong), never the raw email: that's what used to
    # overflow AuditLog.entity_id's String(100) for a long-enough address.
    assert uuid.UUID(row["entity_id"])


async def test_failed_login_for_an_unknown_email_has_no_entity_id(
    client: TestClient, migrated_postgres_dsn: str
) -> None:
    unknown_email = "nobody-in-particular@example.com"
    response = client.post(
        "/api/v1/auth/login", json={"email": unknown_email, "password": "whatever123"}
    )
    assert response.status_code == 401

    engine = create_async_engine(migrated_postgres_dsn)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                select(AuditLog).where(
                    AuditLog.action == "user.login_failed",
                    AuditLog.details["email"].astext == unknown_email,
                )
            )
            row = result.mappings().one_or_none()
    finally:
        await engine.dispose()

    assert row is not None
    assert row["entity_id"] is None
    assert row["user_id"] is None


def test_login_is_case_insensitive_on_email(
    client: TestClient, admin_email: str, admin_password: str
) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": admin_email.upper(), "password": admin_password},
    )
    assert response.status_code == 200, response.text


def test_me_with_a_token_carrying_a_malformed_sub_claim_returns_401(
    client: TestClient, jwt_secret: str, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    """The token is validly signed (so it passes signature/expiry checks)
    but its `sub` isn't a UUID — regression test for an unhandled ValueError
    that used to surface as a 500 instead of 401.
    """
    now = datetime.now(UTC)
    forged = jwt.encode(
        {
            "sub": "not-a-uuid",
            "role": "admin",
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        jwt_secret,
        algorithm="HS256",
    )
    response = client.get("/api/v1/auth/me", headers=auth_headers(forged))
    assert response.status_code == 401


def test_refresh_rotates_token_and_invalidates_the_old_one(
    client: TestClient, admin_email: str, admin_password: str
) -> None:
    login = client.post(
        "/api/v1/auth/login", json={"email": admin_email, "password": admin_password}
    )
    old_refresh_token = login.json()["refresh_token"]

    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh_token})
    assert refreshed.status_code == 200, refreshed.text
    new_body = refreshed.json()
    assert new_body["refresh_token"] != old_refresh_token

    reused = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh_token})
    assert reused.status_code == 401


def test_refresh_with_garbage_token_returns_401(client: TestClient) -> None:
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_logout_revokes_the_refresh_token(
    client: TestClient, admin_email: str, admin_password: str
) -> None:
    login = client.post(
        "/api/v1/auth/login", json={"email": admin_email, "password": admin_password}
    )
    access_token = login.json()["access_token"]
    refresh_token = login.json()["refresh_token"]

    logout = client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refresh_token},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert logout.status_code == 204

    reused = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert reused.status_code == 401


def test_me_returns_the_current_user_with_a_valid_token(
    client: TestClient,
    admin_email: str,
    admin_password: str,
    auth_headers: Callable[[str], dict[str, str]],
) -> None:
    login = client.post(
        "/api/v1/auth/login", json={"email": admin_email, "password": admin_password}
    )
    access_token = login.json()["access_token"]

    me = client.get("/api/v1/auth/me", headers=auth_headers(access_token))
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["email"] == admin_email
    assert body["role"] == "admin"


def test_me_without_a_token_returns_401(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_me_with_a_garbage_token_returns_401(
    client: TestClient, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    response = client.get("/api/v1/auth/me", headers=auth_headers("not-a-real-jwt"))
    assert response.status_code == 401


def test_admin_seeding_is_idempotent(
    client: TestClient, admin_access_token: str, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    """The `client`/`admin_access_token` fixtures already ran `seed_admin_user`
    once each via `create_app()`'s lifespan; assert it never created a
    duplicate row across those app instances.
    """
    response = client.get("/api/v1/users", headers=auth_headers(admin_access_token))
    assert response.status_code == 200, response.text
    admin_rows = [u for u in response.json()["items"] if u["role"] == "admin"]
    assert len(admin_rows) == 1
