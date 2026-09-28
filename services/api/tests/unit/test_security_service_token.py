"""Unit tests for `require_service_token` — calls the dependency directly
with a minimal fake Request, no HTTP app or DB needed. No route wires this
into the surface yet (lands with P1-J3's `/internal/v1/cameras`), but the
"empty must never match empty" branch is security-critical enough to cover
now rather than leave untested until then.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from api.api.errors import APIError
from api.api.security import require_service_token
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request


def _fake_request(service_token: str) -> Request:
    app_state = SimpleNamespace(settings=SimpleNamespace(service_token=service_token))
    scope = {"type": "http", "app": SimpleNamespace(state=app_state)}
    return Request(scope)


async def test_accepts_a_matching_token() -> None:
    request = _fake_request("shared-secret")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="shared-secret")
    await require_service_token(request, credentials)  # does not raise


async def test_rejects_a_mismatched_token() -> None:
    request = _fake_request("shared-secret")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong-token")
    with pytest.raises(APIError):
        await require_service_token(request, credentials)


async def test_rejects_missing_credentials() -> None:
    request = _fake_request("shared-secret")
    with pytest.raises(APIError):
        await require_service_token(request, None)


async def test_rejects_everything_when_unconfigured() -> None:
    """An empty configured token must reject every request — never treat an
    unset expected value as matching an empty presented one.
    """
    request = _fake_request("")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="")
    with pytest.raises(APIError):
        await require_service_token(request, credentials)
