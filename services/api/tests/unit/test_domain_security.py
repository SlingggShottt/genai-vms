"""Unit tests for the pure, service-local auth logic — password hashing
(FR-AUTH-02) and refresh-token generation/hashing. No I/O, no DB.

Access-token JWT tests live in libs/vms_common/tests/unit/test_auth.py —
that logic moved to vms_common.auth (P1-J2 review: generic infra, not
api-specific).
"""

from __future__ import annotations

from api.domain.security import (
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)


def test_hash_password_then_verify_succeeds() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_rejects_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("wrong password", hashed) is False


def test_hash_password_is_salted_and_nondeterministic() -> None:
    a = hash_password("same password")
    b = hash_password("same password")
    assert a != b


def test_verify_password_rejects_garbage_hash_without_raising() -> None:
    assert verify_password("anything", "not-a-real-argon2-hash") is False


def test_generate_refresh_token_is_high_entropy_and_unique() -> None:
    a = generate_refresh_token()
    b = generate_refresh_token()
    assert a != b
    assert len(a) >= 32


def test_hash_refresh_token_is_deterministic() -> None:
    token = generate_refresh_token()
    assert hash_refresh_token(token) == hash_refresh_token(token)


def test_hash_refresh_token_differs_for_different_tokens() -> None:
    assert hash_refresh_token(generate_refresh_token()) != hash_refresh_token(
        generate_refresh_token()
    )
