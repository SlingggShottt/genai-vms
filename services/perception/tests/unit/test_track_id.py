"""Tests for perception.domain.track_id."""

import pytest
from perception.domain.track_id import format_track_id


def test_format_track_id_matches_glossary_convention() -> None:
    assert format_track_id("cam03", 412) == "cam03-t412"


def test_format_track_id_rejects_negative() -> None:
    with pytest.raises(ValueError, match="track_num must be >= 0"):
        format_track_id("cam01", -1)


def test_format_track_id_allows_zero() -> None:
    assert format_track_id("cam01", 0) == "cam01-t0"
