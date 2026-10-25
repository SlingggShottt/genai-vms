"""The envelope of every WebSocket message (design_architecture.md §9).

    {"type": "alert.created", "data": {...}, "ts": "2026-10-05T10:16:14.512Z"}

`type` is one of `alert.created`, `alert.updated`, `camera.status`, `job.progress`,
`incident.ready`; who may receive which is `api.domain.alerts.WS_MESSAGE_ROLES`.
"""

from __future__ import annotations

from vms_common.contracts.ws import WsMessage

__all__ = ["WsMessage"]  # the envelope is a cross-service contract: vms_common.contracts.ws
