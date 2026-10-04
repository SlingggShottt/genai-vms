"""Indexing text into the `knowledge` collection: verified events (`event.v1`) and written
incident reports (`incidentready.v1`) — design §6.2, P4-J4, P6-J3."""

from __future__ import annotations

from datetime import datetime

from aiokafka.structs import ConsumerRecord
from qdrant_client import AsyncQdrantClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vms_common.contracts.event import EventV1
from vms_common.contracts.reasoning import IncidentReadyV1
from vms_common.kafka.consumer import BaseConsumer
from vms_common.logging import get_logger
from vms_common.qdrant.knowledge import (
    DOC_EVENT,
    DOC_INCIDENT,
    KnowledgeDoc,
    KnowledgeEmbedder,
    upsert_docs,
)
from vms_common.qdrant.point_ids import knowledge_point_id

log = get_logger(__name__)


def _ms(ts: datetime) -> int:
    return int(ts.timestamp() * 1000)


def event_doc(event: EventV1) -> KnowledgeDoc | None:
    """The caption the vision model wrote, with the event's type and area so that a query for
    "intrusion in the yard" finds it even when the caption never says so. None when there is
    no caption to index (a `skipped` event)."""
    caption = (event.verification.caption or "").strip()
    if not caption:
        return None
    zone = f" in {event.zone_id}" if event.zone_id else ""
    return KnowledgeDoc(
        point_id=knowledge_point_id(DOC_EVENT, event.event_id),
        text=f"{event.event_type.replace('_', ' ')}{zone} on {event.camera_id}: {caption}",
        payload={
            "doc_type": DOC_EVENT,
            "ref_id": event.event_id,
            "camera_ids": [event.camera_id],
            "ts_start": _ms(event.start_ts),
            "ts_end": _ms(event.end_ts),
            "severity": event.severity,
            "event_type": event.event_type,
        },
    )


def incident_docs(
    incident_id: str,
    report: dict,
    *,
    camera_ids: list[str],
    start: datetime,
    end: datetime,
    severity: str,
    event_type: str,
) -> list[KnowledgeDoc]:
    """One document per section a reader would search for: the headline, each phase, the causal
    chain, the actions."""
    base = {
        "doc_type": DOC_INCIDENT,
        "ref_id": incident_id,
        "camera_ids": camera_ids,
        "ts_start": _ms(start),
        "ts_end": _ms(end),
        "severity": severity,
        "event_type": event_type,
        "title": report.get("title", ""),
    }

    def doc(part: str, body: str) -> KnowledgeDoc:
        return KnowledgeDoc(
            point_id=knowledge_point_id(DOC_INCIDENT, incident_id, part),
            text=f"{report.get('title', '')}. {body}".strip(),
            payload={**base, "part": part},
        )

    docs = []
    if report.get("summary"):
        docs.append(doc("summary", report["summary"]))
    for p in report.get("phase_analysis", []):
        docs.append(doc(f"phase:{p['phase']}", f"{p['phase']}: {p['summary']}"))
    chain = " ".join(s["description"] for s in report.get("causal_chain", []))
    if chain:
        docs.append(doc("causal", chain))
    actions = " ".join(a["action"] for a in report.get("recommended_actions", []))
    if actions:
        docs.append(doc("actions", actions))
    return docs


class EventKnowledgeConsumer(BaseConsumer[EventV1]):
    def __init__(
        self, *, qdrant: AsyncQdrantClient, embedder: KnowledgeEmbedder, **kwargs: object
    ) -> None:
        super().__init__(model=EventV1, **kwargs)  # type: ignore[arg-type]
        self._qdrant, self._embedder = qdrant, embedder

    async def handle(self, message: EventV1, record: ConsumerRecord) -> None:
        doc = event_doc(message)
        if doc is not None:
            await upsert_docs(self._qdrant, self._embedder, [doc])


class IncidentKnowledgeConsumer(BaseConsumer[IncidentReadyV1]):
    def __init__(
        self,
        *,
        qdrant: AsyncQdrantClient,
        embedder: KnowledgeEmbedder,
        session_factory: async_sessionmaker[AsyncSession],
        **kwargs: object,
    ) -> None:
        super().__init__(model=IncidentReadyV1, **kwargs)  # type: ignore[arg-type]
        self._qdrant, self._embedder, self._sessions = qdrant, embedder, session_factory

    async def handle(self, message: IncidentReadyV1, record: ConsumerRecord) -> None:
        if message.status != "generated":
            return
        async with self._sessions() as s:
            row = (
                await s.execute(
                    text(
                        "SELECT report, camera_ids, window_start, window_end, severity, event_type "
                        "FROM reasoning.incidents WHERE id::text = :i AND report IS NOT NULL"
                    ),
                    {"i": message.incident_id},
                )
            ).first()
        if row is None:
            return  # the row is written before the notice; a missing one was deleted since
        docs = incident_docs(
            message.incident_id,
            row[0],
            camera_ids=list(row[1]),
            start=row[2],
            end=row[3],
            severity=row[4],
            event_type=row[5],
        )
        await upsert_docs(self._qdrant, self._embedder, docs)
        log.info("incident_indexed", incident_id=message.incident_id, sections=len(docs))
