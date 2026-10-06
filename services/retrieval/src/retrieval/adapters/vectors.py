"""Qdrant side of retrieval: SigLIP vector search over `frames` and `tracks` with payload
filters taken from the query plan (design §6.2, §10.1)."""

from __future__ import annotations

from datetime import datetime

import numpy as np
from qdrant_client import AsyncQdrantClient, models
from vms_common.qdrant.collections import (
    FRAMES_COLLECTION,
    SIGLIP_VECTOR_NAME,
    TRACKS_COLLECTION,
)

from retrieval.domain.fusion import Hit


def _ms(ts: datetime | None) -> int | None:
    return int(ts.timestamp() * 1000) if ts else None


def _filter(
    *,
    cameras: list[str],
    start: datetime | None,
    end: datetime | None,
    ts_field: str,
    categories: list[str] | None = None,
    category_field: str | None = None,
) -> models.Filter | None:
    must: list[models.Condition] = []
    if cameras:
        must.append(models.FieldCondition(key="camera_id", match=models.MatchAny(any=cameras)))
    lo, hi = _ms(start), _ms(end)
    if lo is not None or hi is not None:
        must.append(models.FieldCondition(key=ts_field, range=models.Range(gte=lo, lte=hi)))
    if categories and category_field:
        must.append(
            models.FieldCondition(key=category_field, match=models.MatchAny(any=categories))
        )
    return models.Filter(must=must) if must else None


class VectorSearch:
    def __init__(self, client: AsyncQdrantClient) -> None:
        self._client = client

    async def frames(
        self,
        vector: np.ndarray,
        *,
        cameras: list[str],
        start: datetime | None,
        end: datetime | None,
        limit: int,
    ) -> list[Hit]:
        res = await self._client.query_points(
            FRAMES_COLLECTION,
            query=vector.tolist(),
            using=SIGLIP_VECTOR_NAME,
            query_filter=_filter(cameras=cameras, start=start, end=end, ts_field="ts"),
            limit=limit,
            with_payload=True,
        )
        hits: list[Hit] = []
        for p in res.points:
            pl = p.payload or {}
            ts = int(pl["ts"])
            hits.append(
                Hit(
                    source="frames",
                    key=f"f:{p.id}",
                    camera_id=pl["camera_id"],
                    start_ms=ts,
                    end_ms=ts,
                    cosine=float(p.score),
                    segment_ids=[pl["segment_id"]] if pl.get("segment_id") else [],
                    keyframe_uri=pl.get("keyframe_uri"),
                    category=None,
                    zones=[],
                )
            )
        return hits

    async def tracks(
        self,
        vector: np.ndarray,
        *,
        cameras: list[str],
        start: datetime | None,
        end: datetime | None,
        categories: list[str],
        limit: int,
        prefer_colors: list[str] | None = None,
        prefer_zones: list[str] | None = None,
        source: str = "tracks",
    ) -> list[Hit]:
        res = await self._client.query_points(
            TRACKS_COLLECTION,
            query=vector.tolist(),
            using=SIGLIP_VECTOR_NAME,
            query_filter=_filter(
                cameras=cameras,
                start=start,
                end=end,
                ts_field="first_ts",
                categories=categories,
                category_field="category",
            ),
            limit=limit,
            with_payload=True,
        )
        hits: list[Hit] = []
        for p in res.points:
            pl = p.payload or {}
            colors = list(pl.get("colors") or [])
            boost = 1.0
            if prefer_colors and set(prefer_colors) & set(colors):
                boost = 1.5  # the detector's colour naming is rough, so a match boosts, not filters
            if prefer_zones and set(prefer_zones) & set(pl.get("zones") or []):
                boost *= 1.5
            hits.append(
                Hit(
                    source=source,  # type: ignore[arg-type]
                    key=f"t:{p.id}",
                    camera_id=pl["camera_id"],
                    start_ms=int(pl["first_ts"]),
                    end_ms=int(pl.get("last_ts") or pl["first_ts"]),
                    cosine=float(p.score),
                    segment_ids=list(pl.get("segment_ids") or []),
                    crop_uri=pl.get("crop_uri"),
                    track_id=pl.get("track_id"),
                    category=pl.get("category"),
                    colors=colors,
                    zones=list(pl.get("zones") or []),
                    boost=boost,
                )
            )
        return hits

    async def keyframe_near(
        self, camera_id: str, ts_ms: int, *, within_s: float = 4.0
    ) -> str | None:
        """The keyframe of `camera_id` closest to `ts_ms` — a window found only through track
        crops has no frame of its own, and a result card should still show the scene."""
        pad = int(within_s * 1000)
        points, _ = await self._client.scroll(
            FRAMES_COLLECTION,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="camera_id", match=models.MatchValue(value=camera_id)
                    ),
                    models.FieldCondition(
                        key="ts", range=models.Range(gte=ts_ms - pad, lte=ts_ms + pad)
                    ),
                ]
            ),
            limit=8,
            with_payload=True,
        )
        if not points:
            return None
        best = min(points, key=lambda p: abs(int((p.payload or {})["ts"]) - ts_ms))
        return (best.payload or {}).get("keyframe_uri")
