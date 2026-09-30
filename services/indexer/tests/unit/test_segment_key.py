from __future__ import annotations

from datetime import UTC, datetime

from indexer.domain.segment_key import build_segment_uri


def test_build_segment_uri_matches_the_documented_key_layout() -> None:
    start_ts = datetime(2026, 10, 5, 10, 15, 0, tzinfo=UTC)
    uri = build_segment_uri("cam03", start_ts, "cam03_20261005T101500Z_000123")
    assert uri == "s3://vms-segments/cam03/2026/10/05/10/cam03_20261005T101500Z_000123.ts"
