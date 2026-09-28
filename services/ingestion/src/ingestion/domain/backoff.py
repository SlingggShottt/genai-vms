"""Reconnect backoff — pure. FR-ING-05: exponential backoff, capped at 30s."""

from __future__ import annotations


def reconnect_backoff_seconds(attempt: int, *, base: float = 1.0, cap: float = 30.0) -> float:
    """1, 2, 4, 8, 16, 30, 30, ... — doubles per attempt, capped at `cap`."""
    if attempt < 1:
        raise ValueError(f"attempt must be >= 1, got {attempt}")
    return min(base * (2 ** (attempt - 1)), cap)
