"""Tests for ingestion.domain.backoff — FR-ING-05: exponential, capped at 30s."""

import pytest
from ingestion.domain.backoff import reconnect_backoff_seconds


@pytest.mark.parametrize(
    ("attempt", "expected"),
    [
        (1, 1.0),
        (2, 2.0),
        (3, 4.0),
        (4, 8.0),
        (5, 16.0),
        (6, 30.0),  # would be 32 uncapped
        (7, 30.0),
        (100, 30.0),
    ],
)
def test_reconnect_backoff_doubles_then_caps(attempt: int, expected: float) -> None:
    assert reconnect_backoff_seconds(attempt) == expected


def test_reconnect_backoff_rejects_non_positive_attempt() -> None:
    with pytest.raises(ValueError, match="attempt must be >= 1"):
        reconnect_backoff_seconds(0)


def test_reconnect_backoff_respects_custom_base_and_cap() -> None:
    assert reconnect_backoff_seconds(1, base=0.5, cap=5.0) == 0.5
    assert reconnect_backoff_seconds(10, base=0.5, cap=5.0) == 5.0
