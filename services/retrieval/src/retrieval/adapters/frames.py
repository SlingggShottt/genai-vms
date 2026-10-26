"""Reads a stored keyframe for "find similar" (P4-J1). Only the keyframes bucket: the retrieval
service holds credentials for every bucket, and a request must not be able to name a recording,
a model or a report and have it embedded."""

from __future__ import annotations

from vms_common.storage.s3 import S3Client

ALLOWED_BUCKETS = ("vms-keyframes",)


class FrameNotAllowedError(ValueError):
    """The uri is not a keyframe this service may read for a request."""


def check_keyframe_uri(uri: str) -> str:
    prefix = "s3://"
    bucket, _, key = (
        uri.removeprefix(prefix).partition("/") if uri.startswith(prefix) else ("", "", "")
    )
    if bucket not in ALLOWED_BUCKETS or not key or ".." in key.split("/"):
        raise FrameNotAllowedError("that is not a stored keyframe")
    return uri


class FrameReader:
    def __init__(self, s3: S3Client) -> None:
        self._s3 = s3

    async def read(self, uri: str) -> bytes:
        return await self._s3.get_bytes(check_keyframe_uri(uri))
