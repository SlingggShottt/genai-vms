"""Turn `core.alerts` rows into what the API shows: the camera's id, the correlation group the
event is in now (following merges), and — when asked — fresh presigned keyframe urls."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from vms_common.storage.s3 import S3Client
from vms_db.models import Alert

from api.adapters.cameras import camera_ids_by_code
from api.adapters.groups import resolve_groups
from api.schemas import AlertOut


async def build_alert_outs(
    session: AsyncSession, alerts: Sequence[Alert], *, s3: S3Client | None = None
) -> list[AlertOut]:
    """`s3=None` leaves `keyframe_urls` empty (WebSocket pushes: no urls on a shared channel)."""
    if not alerts:
        return []
    cameras = await camera_ids_by_code(session, {a.camera_id for a in alerts})
    groups = await resolve_groups(session, {a.group_id for a in alerts if a.group_id})
    outs: list[AlertOut] = []
    for alert in alerts:
        urls = [await s3.presign_get(uri) for uri in alert.keyframe_uris] if s3 else []
        outs.append(
            AlertOut.from_model(
                alert,
                group=groups.get(alert.group_id) if alert.group_id else None,
                camera_id=cameras.get(alert.camera_id),
                keyframe_urls=urls,
            )
        )
    return outs
