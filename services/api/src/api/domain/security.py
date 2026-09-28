"""Pure auth logic — no I/O, unit tests target this module directly.

Password hashing (Argon2id, FR-AUTH-02) and refresh-token generation/
hashing. Access-token JWT encode/decode lives in `vms_common.auth` — it's
generic infra with no service-specific state, unlike this module, which
only `api` (the one service that manages user accounts) ever needs.

Argon2id is deliberately slow (that's the point, for password brute-force
resistance) — `hash_password`/`verify_password` are CPU-bound and must be
called via `asyncio.to_thread` from any `async def`, never awaited directly
(style_guide.md §A.1: no blocking I/O/CPU work inside `async def`). Refresh
tokens are high-entropy random secrets hashed with SHA-256 for storage/
lookup (`core.refresh_tokens.token_hash`) instead — a 256-bit random token
needs neither Argon2's slowness nor its salting, and SHA-256 keeps the hash
equality-comparable for a DB lookup.
"""

from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHash):
        return False
    return True


def generate_refresh_token() -> str:
    """A 256-bit random opaque secret — never a JWT, never decoded, only compared by hash."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
