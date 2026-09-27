"""Tests for perception.domain.segmenting — matches design_architecture.md
§5.3's worked twinready.v1 example exactly."""

from datetime import UTC, datetime

from perception.domain.segmenting import (
    build_crop_key,
    build_embeddings_key,
    build_twin_key,
    parse_segment_seq,
)

START = datetime(2026, 10, 5, 10, 15, 0, tzinfo=UTC)
SEGMENT_ID = "cam03_20261005T101500Z_000123"


def test_parse_segment_seq() -> None:
    assert parse_segment_seq(SEGMENT_ID) == 123


def test_build_twin_key_matches_design_doc_example() -> None:
    assert build_twin_key("cam03", START, SEGMENT_ID) == "cam03/2026/10/05/10/000123.json"


def test_build_embeddings_key_matches_design_doc_example() -> None:
    assert build_embeddings_key("cam03", START, SEGMENT_ID) == "cam03/2026/10/05/10/000123.npz"


def test_build_crop_key() -> None:
    key = build_crop_key("cam03", START, SEGMENT_ID, "cam03-t412")
    assert key == "cam03/2026/10/05/10/000123/cam03-t412.jpg"
