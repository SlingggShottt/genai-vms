"""Picking frames. Pure."""

from __future__ import annotations

from datetime import datetime
from typing import TypeVar

T = TypeVar("T")


def pick_evenly(items: list[T], n: int) -> list[T]:
    """`n` items spread across the list, first and last included; all of them if fewer."""
    if n <= 0 or not items:
        return []
    if len(items) <= n:
        return list(items)
    if n == 1:
        return [items[len(items) // 2]]
    step = (len(items) - 1) / (n - 1)
    return [items[round(i * step)] for i in range(n)]


def within(items: list[T], start: datetime, end: datetime, ts_of) -> list[T]:
    return [i for i in items if start <= ts_of(i) <= end]


def nearest(items: list[T], at: datetime, n: int, ts_of) -> list[T]:
    """The `n` items closest in time to `at`, back in time order."""
    best = sorted(items, key=lambda i: abs((ts_of(i) - at).total_seconds()))[:n]
    return sorted(best, key=ts_of)
