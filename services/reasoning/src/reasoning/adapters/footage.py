"""Where a job's pictures come from: the twin documents of the segments covering its window
(each lists the sampled keyframes with their times) and the keyframe JPEGs in object storage.
No video is decoded."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from vms_common.contracts.twin import TwinV1
from vms_common.logging import get_logger
from vms_common.storage.s3 import S3Client

from reasoning.adapters.store import ReasoningStore

log = get_logger(__name__)


@dataclass(frozen=True)
class FootFrame:
    camera_id: str
    ts: datetime
    uri: str
    persons: int = 0


class Footage:
    def __init__(self, store: ReasoningStore, s3: S3Client) -> None:
        self._store = store
        self._s3 = s3
        self._cache: dict[str, bytes] = {}

    async def frames(self, camera_id: str, start: datetime, end: datetime) -> list[FootFrame]:
        segs = await self._store.segments(camera_id, start - timedelta(seconds=2), end)

        async def load(uri: str) -> TwinV1 | None:
            try:
                return TwinV1.model_validate(json.loads(await self._s3.get_bytes(uri)))
            except Exception as exc:  # a lost twin leaves a gap, it does not fail the job
                log.warning("twin_unreadable", uri=uri, error=str(exc))
                return None

        twins = await asyncio.gather(*(load(s.twin_uri) for s in segs))
        out: list[FootFrame] = []
        for twin in twins:
            if twin is None:
                continue
            for fr in twin.frames:
                if start <= fr.ts <= end:
                    persons = sum(1 for o in fr.objects if o.category == "person")
                    out.append(FootFrame(camera_id, fr.ts, fr.keyframe_uri, persons))
        out.sort(key=lambda f: f.ts)
        return out

    async def image(self, uri: str) -> bytes:
        if uri not in self._cache:
            self._cache[uri] = await self._s3.get_bytes(uri)
        return self._cache[uri]

    async def keep(self, uri: str, dest_uri: str) -> None:
        """Copy a keyframe somewhere that is not subject to the keyframe bucket's retention."""
        await self._s3.put_bytes(dest_uri, await self.image(uri), content_type="image/jpeg")
