"""Unit tests for access-token JWT encode/decode (FR-AUTH-01). No I/O.

Moved here from services/api during P1-J2 review: this logic has no
api-specific state (it's a pure function of token/secret/algorithm), so it
belongs in vms_common alongside JWTSettings, not duplicated by the next
service that needs to issue or verify a token.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from vms_common.auth import InvalidTokenError, decode_access_token, encode_access_token

SECRET = "unit-test-secret-at-least-32-bytes-long"  # noqa: S105


def test_encode_then_decode_access_token_round_trips() -> None:
    token = encode_access_token(
        user_id="11111111-1111-7111-8111-111111111111",
        role="admin",
        secret=SECRET,
        algorithm="HS256",
        expires_minutes=15,
    )
    payload = decode_access_token(token, secret=SECRET, algorithm="HS256")
    assert payload["sub"] == "11111111-1111-7111-8111-111111111111"
    assert payload["role"] == "admin"
    assert payload["type"] == "access"


def test_decode_access_token_rejects_wrong_secret() -> None:
    token = encode_access_token(
        user_id="u1", role="viewer", secret=SECRET, algorithm="HS256", expires_minutes=15
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, secret="a-different-secret", algorithm="HS256")


def test_decode_access_token_rejects_expired_token() -> None:
    now = datetime.now(UTC)
    expired_payload = {
        "sub": "u1",
        "role": "viewer",
        "type": "access",
        "iat": now - timedelta(minutes=30),
        "exp": now - timedelta(minutes=15),
    }
    expired_token = jwt.encode(expired_payload, SECRET, algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        decode_access_token(expired_token, secret=SECRET, algorithm="HS256")


def test_decode_access_token_rejects_non_access_token_type() -> None:
    now = datetime.now(UTC)
    refresh_shaped_payload = {
        "sub": "u1",
        "role": "viewer",
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(minutes=15),
    }
    token = jwt.encode(refresh_shaped_payload, SECRET, algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, secret=SECRET, algorithm="HS256")


def test_encode_access_token_rejects_an_empty_secret() -> None:
    """A blank HMAC key is forgeable by anyone — must fail loudly, not
    silently sign a token no one configured a real secret for.
    """
    with pytest.raises(InvalidTokenError):
        encode_access_token(
            user_id="u1", role="admin", secret="", algorithm="HS256", expires_minutes=15
        )


def test_decode_access_token_rejects_an_empty_secret() -> None:
    # PyJWT itself refuses to sign with an empty key (InvalidKeyError), so a
    # token actually forged that way can't exist to decode — this instead
    # confirms decode_access_token's own guard rejects an empty secret
    # outright, before ever calling jwt.decode. Any validly-signed token
    # works here; its signature is irrelevant to what's under test.
    token = encode_access_token(
        user_id="u1", role="admin", secret=SECRET, algorithm="HS256", expires_minutes=15
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, secret="", algorithm="HS256")
