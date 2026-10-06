"""Retrieval's reader of the `knowledge` collection: verified-event captions and incident-report
sections found by meaning and by words (dense + BM25, fused server-side), as hits for the search
fusion; and the "similar incidents" lookup."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from qdrant_client import AsyncQdrantClient
from vms_common.logging import get_logger
from vms_common.qdrant.knowledge import (
    DOC_EVENT,
    DOC_INCIDENT,
    KnowledgeEmbedder,
    search_docs,
)

from retrieval.domain.fusion import Hit

log = get_logger(__name__)


def make_embedder(cache_dir: str) -> KnowledgeEmbedder:
    return KnowledgeEmbedder(cache_dir=cache_dir or str(Path.home() / ".cache" / "vms-fastembed"))


def _ms(ts: datetime | None) -> int | None:
    return int(ts.timestamp() * 1000) if ts else None


class KnowledgeSearch:
    def __init__(self, client: AsyncQdrantClient, embedder: KnowledgeEmbedder) -> None:
        self._client = client
        self._embedder = embedder

    @property
    def loaded(self) -> bool:
        return self._embedder.loaded

    async def hits(
        self,
        query: str,
        *,
        cameras: list[str],
        start: datetime | None,
        end: datetime | None,
        limit: int,
    ) -> list[Hit]:
        """Event captions and incident sections matching `query`, as search hits. Keys match
        the Postgres caption search (`e:<event id>`), so one event found both ways counts once."""
        points = await search_docs(
            self._client,
            self._embedder,
            query,
            doc_types=[DOC_EVENT, DOC_INCIDENT],
            camera_ids=cameras or None,
            since_ms=_ms(start),
            until_ms=_ms(end),
            limit=limit,
        )
        out: list[Hit] = []
        for p in points:
            pl = p.payload or {}
            cams = pl.get("camera_ids") or []
            if not cams:
                continue
            is_event = pl.get("doc_type") == DOC_EVENT
            ref = pl["ref_id"]
            part = pl.get("part", "")
            out.append(
                Hit(
                    source="events",
                    key=f"e:{ref}" if is_event else f"i:{ref}:{part}",
                    camera_id=cams[0],
                    start_ms=int(pl["ts_start"]),
                    end_ms=int(pl["ts_end"]),
                    cosine=float(p.score),
                    event_id=ref if is_event else None,
                    incident_id=None if is_event else ref,
                    caption=pl.get("text") if is_event else pl.get("title"),
                    boost=1.2,
                )
            )
        return out

    async def similar_incidents(
        self, incident_id: str, title: str, summary: str, event_type: str, *, limit: int = 5
    ) -> list[dict]:
        """Other written incidents closest to this one, best first. The same event type counts
        for a little extra: two intrusions are more alike than an intrusion and a crowd."""
        points = await search_docs(
            self._client,
            self._embedder,
            f"{title}. {summary}",
            doc_types=[DOC_INCIDENT],
            exclude_ref_ids=[incident_id],
            limit=40,
        )
        best: dict[str, dict] = {}
        for p in points:
            pl = p.payload or {}
            ref = pl["ref_id"]
            score = float(p.score) * (1.25 if pl.get("event_type") == event_type else 1.0)
            if ref not in best or score > best[ref]["raw"]:
                best[ref] = {
                    "incident_id": ref,
                    "title": pl.get("title", ""),
                    "severity": pl.get("severity"),
                    "event_type": pl.get("event_type"),
                    "camera_ids": pl.get("camera_ids", []),
                    "ts_start": pl.get("ts_start"),
                    "raw": score,
                }
        ranked = sorted(best.values(), key=lambda d: -d["raw"])[:limit]
        top = ranked[0]["raw"] if ranked else 1.0
        for d in ranked:
            d["score"] = round(d.pop("raw") / top, 3)
        return ranked
