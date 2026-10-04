"""Fetches the keyframes the VLM gate shows the model (P3-D4)."""

from __future__ import annotations

from collections.abc import Sequence

from botocore.exceptions import BotoCoreError, ClientError
from vms_common.logging import get_logger
from vms_common.storage.s3 import S3Client
from vms_common.storage.uri import InvalidS3UriError

from events.domain.evidence import EvidenceFrame

log = get_logger(__name__)


class S3KeyframeSource:
    def __init__(self, s3: S3Client) -> None:
        self._s3 = s3

    async def load(self, frames: Sequence[EvidenceFrame]) -> list[tuple[EvidenceFrame, bytes]]:
        """The JPEG of each of `frames`, in order. A keyframe that cannot be read (expired by a
        lifecycle rule, a storage hiccup) is left out and logged: the gate judges on what it has
        and treats having nothing as the model being unavailable."""
        loaded: list[tuple[EvidenceFrame, bytes]] = []
        for frame in frames:
            try:
                loaded.append((frame, await self._s3.get_bytes(frame.keyframe_uri)))
            except (BotoCoreError, ClientError, InvalidS3UriError) as exc:
                log.warning("keyframe_unreadable", uri=frame.keyframe_uri, error=str(exc))
        return loaded
