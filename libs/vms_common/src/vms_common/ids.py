"""UUIDv7 generation (RFC 9562) — used for every database row id.

Python's stdlib gets uuid7() in 3.14; until then (style_guide.md §A.1 pins
Python 3.11) this implements it directly rather than adding a dependency:
a 48-bit big-endian Unix millisecond timestamp, the version/variant bits,
and 74 bits of cryptographically random tail.
"""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """Generate a time-ordered UUID version 7.

    Layout (128 bits): 48-bit unix_ts_ms | 4-bit version (0111) |
    12-bit rand_a | 2-bit variant (10) | 62-bit rand_b.
    """
    unix_ts_ms = time.time_ns() // 1_000_000
    ts_bytes = unix_ts_ms.to_bytes(6, byteorder="big")

    buf = bytearray(16)
    buf[0:6] = ts_bytes
    buf[6:16] = os.urandom(10)

    buf[6] = (buf[6] & 0x0F) | 0x70  # version 7 in the high nibble of byte 6
    buf[8] = (buf[8] & 0x3F) | 0x80  # variant 10 in the high 2 bits of byte 8

    return uuid.UUID(bytes=bytes(buf))


def uuid7_str() -> str:
    """uuid7() as a string — convenience for id fields/columns."""
    return str(uuid7())
