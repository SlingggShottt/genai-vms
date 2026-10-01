"""Checkpointing of the per-camera engine state, so a restart resumes a
half-finished loitering stay or crowd instead of starting its clock over
(same idea as perception's ByteTrack checkpoints in Redis, P2-D2).

The worker saves state only **after** the candidates it produced are durably
written, and the engine skips twins at or before the saved
`last_segment_end` — so a crash between the two steps replays the twin
harmlessly (see `events.domain.engine`).
"""

from __future__ import annotations

from typing import Protocol

from pydantic import ValidationError
from redis.asyncio import Redis
from vms_common.logging import get_logger

from events.domain.state import CameraState

log = get_logger(__name__)

KEY_PREFIX = "events:state:"


class StateStore(Protocol):
    async def load(self, camera_id: str) -> CameraState | None: ...

    async def save(self, state: CameraState) -> None: ...


class MemoryStateStore:
    """In-process store — tests, and a fallback that loses state on restart."""

    def __init__(self) -> None:
        self._states: dict[str, str] = {}

    async def load(self, camera_id: str) -> CameraState | None:
        raw = self._states.get(camera_id)
        return CameraState.model_validate_json(raw) if raw is not None else None

    async def save(self, state: CameraState) -> None:
        self._states[state.camera_id] = state.model_dump_json()


class RedisStateStore:
    """One JSON document per camera under `events:state:<camera_id>`.

    A TTL bounds the key for cameras that disappear for good; an unreadable
    document (e.g. written by an incompatible version) is discarded with a
    warning rather than wedging the consumer.
    """

    def __init__(self, client: Redis, *, ttl_seconds: int) -> None:
        self._client = client
        self._ttl_seconds = ttl_seconds

    async def load(self, camera_id: str) -> CameraState | None:
        raw = await self._client.get(KEY_PREFIX + camera_id)
        if raw is None:
            return None
        try:
            return CameraState.model_validate_json(raw)
        except (ValidationError, ValueError) as exc:
            log.warning(
                "events_state_unreadable_starting_fresh", camera_id=camera_id, error=str(exc)
            )
            return None

    async def save(self, state: CameraState) -> None:
        await self._client.set(
            KEY_PREFIX + state.camera_id, state.model_dump_json(), ex=self._ttl_seconds
        )
