"""Entrypoint for the events service: a Kafka consumer turning `twinready.v1` into rule-engine
candidates in `events.candidates` (P3-D1), and beside it the VLM verification gate turning
candidates into `events.events` and `event.v1` (P3-D4).
"""

from __future__ import annotations

import asyncio
import sys
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from vms_common.contracts.twinready import TwinReadyV1
from vms_common.kafka.producer import KafkaProducerClient
from vms_common.llm import LLMGateway
from vms_common.logging import configure_logging, get_logger
from vms_common.metrics import serve as serve_metrics
from vms_common.redis import get_redis_client
from vms_common.storage.s3 import S3Client
from vms_db.session import create_engine, create_session_factory

from events.adapters.event_store import PostgresEventStore
from events.adapters.keyframes import S3KeyframeSource
from events.adapters.publisher import KafkaEventPublisher
from events.adapters.rules_loader import load_rules_config
from events.adapters.state_store import RedisStateStore
from events.adapters.zones_source import resolve_zones
from events.domain.rules import registered_rules
from events.domain.verification import GatePolicy
from events.settings import EventsSettings
from events.verifier import Verifier, VerifierOptions
from events.worker import EventsConsumer

log = get_logger(__name__)

# Singular "twin" topic name, schema_version "twinready.v1" — same naming quirk as
# the indexer (design_architecture.md §5.2).
TWIN_TOPIC = "vms.twin.v1"
ZONES_REFRESH_STARTUP_GRACE_S = 0.1  # let the first refresh populate the cache before consuming


async def _amain() -> None:
    configure_logging()
    serve_metrics(9104)  # Prometheus scrape port, design §15
    settings = EventsSettings()

    try:
        rules_config = load_rules_config(settings.rules_path)
    except (OSError, ValueError) as exc:  # missing file, bad YAML, or a ValidationError
        detail = exc.errors() if isinstance(exc, ValidationError) else str(exc)
        log.error("rules_config_invalid", path=settings.rules_path, error=detail)
        sys.exit(f"events: cannot start — bad rules config {settings.rules_path}: {exc}")
    log.info(
        "rules_loaded",
        path=settings.rules_path,
        rules=sorted(registered_rules()),
        overrides=len(rules_config.overrides),
    )

    s3 = S3Client(
        endpoint_url=settings.storage.endpoint_url,
        access_key=settings.storage.access_key,
        secret_key=settings.storage.secret_key,
        region=settings.storage.region,
    )
    engine = create_engine(settings.db)
    session_factory = create_session_factory(engine)
    redis_client = get_redis_client(settings.redis)
    state_store = RedisStateStore(redis_client, ttl_seconds=settings.state_ttl_seconds)

    zones_cache: dict[str, list] = {"zones": []}

    async def refresh_zones() -> None:
        while True:
            try:
                zones_cache["zones"] = await resolve_zones(
                    api_base_url=settings.api_base_url,
                    service_token=settings.service_token,
                    yaml_fallback_path=settings.zones_yaml_fallback,
                )
            except Exception as exc:  # noqa: BLE001 - keep the last-known zones on any failure
                log.warning("zones_refresh_failed", error=str(exc))
            await asyncio.sleep(settings.zones_refresh_seconds)

    refresh_task = asyncio.create_task(refresh_zones())
    await asyncio.sleep(ZONES_REFRESH_STARTUP_GRACE_S)

    consumer = EventsConsumer(
        topic=TWIN_TOPIC,
        group_id=settings.consumer_group,
        bootstrap_servers=settings.kafka.bootstrap_servers,
        model=TwinReadyV1,
        dlq_topic=settings.kafka.dlq_topic,
        s3=s3,
        session_factory=session_factory,
        state_store=state_store,
        get_zones=lambda: zones_cache["zones"],
        config=rules_config,
        site_tz=ZoneInfo(settings.site_timezone),
    )

    gateway = LLMGateway.from_settings(settings.llm, redis=redis_client)
    log.info("llm_gateway_ready", profile=gateway.profile)
    verifier_task: asyncio.Task | None = None
    try:
        async with (
            KafkaProducerClient(bootstrap_servers=settings.kafka.bootstrap_servers) as producer,
            consumer,
        ):
            verifier = Verifier(
                gateway=gateway,
                store=PostgresEventStore(session_factory),
                publisher=KafkaEventPublisher(producer, topic=settings.events_topic),
                keyframes=S3KeyframeSource(s3),
                rules=rules_config,
                policy=GatePolicy(
                    min_confidence=settings.verify_min_confidence,
                    unsure_accepted_up_to=settings.verify_unsure_accepted_up_to,
                    hold_from=settings.verify_hold_from,
                    hold_max_age_s=settings.verify_hold_max_age_seconds,
                ),
                options=VerifierOptions(
                    batch_size=settings.verify_batch_size,
                    poll_s=settings.verify_poll_seconds,
                    lease_s=settings.verify_lease_seconds,
                    open_after_s=settings.verify_open_after_seconds,
                    max_age_s=settings.verify_max_age_seconds,
                    retry_base_s=settings.verify_retry_base_seconds,
                    retry_cap_s=settings.verify_retry_cap_seconds,
                ),
            )
            verifier_task = asyncio.create_task(verifier.run(), name="verifier")
            await consumer.run()
    finally:
        if verifier_task is not None:
            verifier_task.cancel()
            await asyncio.gather(verifier_task, return_exceptions=True)
        refresh_task.cancel()
        await gateway.aclose()
        await engine.dispose()
        await redis_client.aclose()


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        log.info("events_stopped")


if __name__ == "__main__":
    main()
