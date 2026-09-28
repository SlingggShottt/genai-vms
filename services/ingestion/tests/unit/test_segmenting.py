"""Tests for ingestion.domain.segmenting — pure key/id layout, no I/O."""

from datetime import UTC, datetime

from ingestion.domain.segmenting import (
    build_keyframe_key,
    build_keyframes_prefix,
    build_segment_id,
    build_segment_key,
)


def test_build_segment_id_matches_srs_format() -> None:
    start = datetime(2026, 10, 5, 10, 15, 0, tzinfo=UTC)

    segment_id = build_segment_id("cam03", start, 123)

    assert segment_id == "cam03_20261005T101500Z_000123"


def test_build_segment_key_matches_bucket_layout() -> None:
    start = datetime(2026, 10, 5, 10, 15, 0, tzinfo=UTC)
    segment_id = build_segment_id("cam03", start, 123)

    key = build_segment_key("cam03", start, segment_id)

    assert key == "cam03/2026/10/05/10/cam03_20261005T101500Z_000123.ts"


def test_build_keyframes_prefix_matches_bucket_layout() -> None:
    start = datetime(2026, 10, 5, 10, 15, 0, tzinfo=UTC)

    prefix = build_keyframes_prefix("cam03", start, 123)

    assert prefix == "cam03/2026/10/05/10/000123/"


def test_build_keyframe_key_appends_zero_padded_index() -> None:
    prefix = "cam03/2026/10/05/10/000123/"

    assert build_keyframe_key(prefix, 1) == "cam03/2026/10/05/10/000123/0001.jpg"
    assert build_keyframe_key(prefix, 42) == "cam03/2026/10/05/10/000123/0042.jpg"


def test_segment_id_is_stable_across_midnight_and_month_boundaries() -> None:
    start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

    segment_id = build_segment_id("cam01", start, 0)
    key = build_segment_key("cam01", start, segment_id)

    assert segment_id == "cam01_20260101T000000Z_000000"
    assert key == "cam01/2026/01/01/00/cam01_20260101T000000Z_000000.ts"
