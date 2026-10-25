"""Turn `events.events` rows into what the API shows: the camera's id, the correlation group the
event is in now, the alert raised for it, and — for one event — fresh presigned keyframe urls."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from vms_common.storage.s3 import S3Client
from vms_db.models import Event

from api.adapters.cameras import camera_ids_by_code
from api.adapters.events import alert_ids_of_events, groups_of_events
from api.schemas import EventOut


async def build_event_outs(
    session: AsyncSession, events: Sequence[Event], *, s3: S3Client | None = None
) -> list[EventOut]:
    """`s3=None` leaves `keyframe_urls` empty (the list carries counts, the detail the urls)."""
    if not events:
        return []
    ids = [e.id for e in events]
    cameras = await camera_ids_by_code(session, {e.camera_id for e in events})
    groups = await groups_of_events(session, ids)
    alerts = await alert_ids_of_events(session, ids)
    outs: list[EventOut] = []
    for event in events:
        urls = [await s3.presign_get(uri) for uri in event.keyframe_uris] if s3 else []
        outs.append(
            EventOut.from_model(
                event,
                group=groups.get(event.id),
                camera_id=cameras.get(event.camera_id),
                alert_id=alerts.get(event.id),
                keyframe_urls=urls,
            )
        )
    return outs
