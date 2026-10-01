"""Entrypoint for the events service: one Kafka consumer turning
`twinready.v1` into rule-engine candidates in `events.candidates` (P3-D1).
"""

from __future__ import annotations

import asyncio
import sys
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from vms_common.contracts.twinready import TwinReadyV1
from vms_common.logging import configure_logging, get_logger
from vms_common.redis import get_redis_client
from vms_common.storage.s3 import S3Client
from vms_db.session import create_engine, create_session_factory

from events.adapters.rules_loader import load_rules_config
from events.adapters.state_store import RedisStateStore
from events.adapters.zones_source import resolve_zones
from events.domain.rules import registered_rules
from events.settings import EventsSettings
from events.worker import EventsConsumer

log = get_logger(__name__)

# Singular "twin" topic name, schema_version "twinready.v1" — same naming quirk as
# the indexer (design_architecture.md §5.2).
TWIN_TOPIC = "vms.twin.v1"
ZONES_REFRESH_STARTUP_GRACE_S = 0.1  # let the first refresh populate the cache before consuming


async def _amain() -> None:
    configure_logging()
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

    try:
        async with consumer:
            await consumer.run()
    finally:
        refresh_task.cancel()
        await engine.dispose()
        await redis_client.aclose()


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        log.info("events_stopped")


if __name__ == "__main__":
    main()
