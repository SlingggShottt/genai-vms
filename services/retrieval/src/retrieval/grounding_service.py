"""Turns "the thing the search matched in this result" into masks: finds the keyframe's boxes in
the twin, asks SAM for masks, caches them (design §10.2)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from vms_common.contracts.twin import TwinV1
from vms_common.logging import get_logger
from vms_common.storage.s3 import S3Client

from retrieval.adapters.catalog import Catalog
from retrieval.adapters.grounding import Grounder, MaskResult, cache_key, dump, rle_encode

log = get_logger(__name__)

MAX_BOXES = 3


@dataclass(frozen=True)
class GroundingRequest:
    keyframe_uri: str
    segment_ids: list[str]
    track_ids: list[str]


class GroundingService:
    def __init__(self, grounder: Grounder, s3: S3Client, catalog: Catalog, bucket: str) -> None:
        self._grounder = grounder
        self._s3 = s3
        self._catalog = catalog
        self._bucket = bucket

    async def _boxes(
        self, req: GroundingRequest
    ) -> list[tuple[str | None, str | None, tuple[float, float, float, float]]]:
        """(track id, category, normalised box) of the matched objects in this keyframe — the
        tracks the search matched, else the most confident people."""
        uris = await self._catalog.twin_uris(req.segment_ids)
        for uri in uris.values():
            try:
                twin = TwinV1.model_validate(json.loads(await self._s3.get_bytes(uri)))
            except Exception as exc:
                log.warning("twin_unreadable", uri=uri, error=str(exc))
                continue
            frame = next((f for f in twin.frames if f.keyframe_uri == req.keyframe_uri), None)
            if frame is None:
                continue
            wanted = [o for o in frame.objects if o.track_id in req.track_ids]
            chosen = wanted or sorted(
                (o for o in frame.objects if o.category == "person"), key=lambda o: -o.conf
            )
            return [(o.track_id, o.category, tuple(o.bbox)) for o in chosen[:MAX_BOXES]]
        return []

    async def masks(self, req: GroundingRequest) -> dict:
        boxes = await self._boxes(req)
        if not boxes:
            return {"width": 0, "height": 0, "masks": []}
        key = f"{self._bucket}/{cache_key(req.keyframe_uri, [b[2] for b in boxes])}.json"
        uri = f"s3://{key}"
        try:
            return json.loads(await self._s3.get_bytes(uri))
        except Exception:  # noqa: S110 - a cache miss is the normal first request
            pass
        image = await self._s3.get_bytes(req.keyframe_uri)
        arrays = await asyncio.to_thread(self._grounder.segment, image, [b[2] for b in boxes])
        height, width = arrays[0].shape
        results = [
            MaskResult(tid, cat, box, rle_encode(m))
            for (tid, cat, box), m in zip(boxes, arrays, strict=True)
        ]
        payload = dump(results, width, height)
        try:
            await self._s3.put_bytes(uri, payload, content_type="application/json")
        except Exception as exc:  # the mask is still good; only the cache write failed
            log.warning("mask_cache_write_failed", error=str(exc))
        return json.loads(payload)
