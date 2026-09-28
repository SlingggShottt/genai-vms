"""Tests for vms_common.storage.uri — pure s3:// URI parsing (no I/O)."""

import pytest
from vms_common.storage.uri import InvalidS3UriError, build_uri, parse_uri


def test_parse_uri_splits_bucket_and_key() -> None:
    loc = parse_uri("s3://vms-segments/cam03/2026/10/05/10/seg_000123.ts")
    assert loc.bucket == "vms-segments"
    assert loc.key == "cam03/2026/10/05/10/seg_000123.ts"


def test_parse_uri_round_trips_through_build_uri() -> None:
    original = "s3://vms-twins/cam03/2026/10/05/10/000123.json"
    loc = parse_uri(original)
    assert build_uri(loc.bucket, loc.key) == original


@pytest.mark.parametrize(
    "bad_uri",
    [
        "https://example.com/not-s3",
        "s3://bucket-with-no-key",
        "s3:///missing-bucket",
    ],
)
def test_parse_uri_rejects_malformed_uris(bad_uri: str) -> None:
    with pytest.raises(InvalidS3UriError):
        parse_uri(bad_uri)


def test_build_uri_rejects_leading_slash_key() -> None:
    with pytest.raises(InvalidS3UriError):
        build_uri("bucket", "/leading-slash-key")


def test_build_uri_rejects_empty_bucket() -> None:
    with pytest.raises(InvalidS3UriError):
        build_uri("", "some/key.json")
