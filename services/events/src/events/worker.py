"""Consumes `twinready.v1`, runs the rule engine over the segment's digital
twin and persists the resulting candidates (P3-D1).

Order of effects (design §5.1 "consumers commit offsets after idempotent
write"): fetch twin -> run engine -> upsert candidates -> save engine state ->
(base class) commit offset. Each step is safe to redo: candidate ids are
deterministic and the upsert is monotonic, and the engine skips a twin its
saved state already covers.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import tzinfo

from aiokafka.structs import ConsumerRecord
from sqlalchemy.ext.asyncio import async_sessionmaker
from vms_common.contracts.twin import TwinV1
from vms_common.contracts.twinready import TwinReadyV1
from vms_common.contracts.zones import ZoneInternal
from vms_common.kafka.consumer import BaseConsumer
from vms_common.logging import bind_context, clear_context, get_logger
from vms_common.storage.s3 import S3Client
from vms_db.session import session_scope

from events.adapters.candidate_repository import upsert_candidates
from events.adapters.state_store import StateStore
from events.domain.config import RulesConfig
from events.domain.engine import process_twin
from events.domain.state import CameraState
from events.metrics import candidates_total

log = get_logger(__name__)


class EventsConsumer(BaseConsumer[TwinReadyV1]):
    def __init__(
        self,
        *,
        s3: S3Client,
        session_factory: async_sessionmaker,
        state_store: StateStore,
        get_zones: Callable[[], list[ZoneInternal]],
        config: RulesConfig,
        site_tz: tzinfo,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._s3 = s3
        self._session_factory = session_factory
        self._state_store = state_store
        self._get_zones = get_zones
        self._config = config
        self._site_tz = site_tz

    async def handle(self, message: TwinReadyV1, record: ConsumerRecord) -> None:
        bind_context(segment_id=message.segment_id, camera_id=message.camera_id)
        try:
            twin = TwinV1.model_validate_json(await self._s3.get_bytes(message.twin_uri))
            state = await self._state_store.load(message.camera_id) or CameraState(
                camera_id=message.camera_id
            )

            outcome = process_twin(
                state, twin, zones=self._get_zones(), config=self._config, site_tz=self._site_tz
            )
            if outcome.skipped:
                log.info("twin_already_evaluated", last_segment_end=state.last_segment_end)
                return

            if outcome.updates:
                async with session_scope(self._session_factory) as session:
                    created = await upsert_candidates(session, outcome.updates)
                for update in created:
                    candidates_total.labels(rule=update.rule_id).inc()
                    log.info(
                        "candidate_created",
                        candidate_id=str(update.id),
                        rule_id=update.rule_id,
                        zone=update.zone_name,
                        tracks=len(update.track_ids),
                        start_ts=update.start_ts.isoformat(),
                    )

            # Only after the candidates are durable (see module docstring).
            await self._state_store.save(outcome.state)
            log.info(
                "twin_evaluated",
                frames=len(twin.frames),
                updates=len(outcome.updates),
                open_episodes=len(outcome.state.episodes),
            )
        finally:
            clear_context()
