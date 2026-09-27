"""`s3://` URI parsing/building — pure functions, no I/O.

Matches the bucket layout in design_architecture.md §6.3, e.g.
`s3://vms-segments/cam03/2026/10/05/10/cam03_20261005T101500Z_000123.ts`.
"""

from __future__ import annotations

from dataclasses import dataclass

_PREFIX = "s3://"


class InvalidS3UriError(ValueError):
    """Raised when a string is not a well-formed s3://bucket/key URI."""


@dataclass(frozen=True)
class S3Location:
    bucket: str
    key: str

    @property
    def uri(self) -> str:
        return f"{_PREFIX}{self.bucket}/{self.key}"


def parse_uri(uri: str) -> S3Location:
    """Parse `s3://bucket/key/with/slashes` into an `S3Location`."""
    if not uri.startswith(_PREFIX):
        raise InvalidS3UriError(f"not an s3:// uri: {uri!r}")
    rest = uri[len(_PREFIX) :]
    if "/" not in rest:
        raise InvalidS3UriError(f"missing key in s3:// uri: {uri!r}")
    bucket, key = rest.split("/", 1)
    if not bucket or not key:
        raise InvalidS3UriError(f"empty bucket or key in s3:// uri: {uri!r}")
    return S3Location(bucket=bucket, key=key)


def build_uri(bucket: str, key: str) -> str:
    """Build an `s3://bucket/key` URI."""
    if not bucket:
        raise InvalidS3UriError("bucket must not be empty")
    if not key or key.startswith("/"):
        raise InvalidS3UriError(f"key must be non-empty and not start with '/': {key!r}")
    return S3Location(bucket=bucket, key=key).uri
