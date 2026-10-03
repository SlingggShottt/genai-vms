"""Entrypoint for the correlation service: one Kafka consumer grouping `event.v1` into
correlation groups plus a sweeper that closes and announces them (P3-J2)."""

from __future__ import annotations

import asyncio
import sys

from pydantic import ValidationError
from vms_common.contracts.event import EventV1
from vms_common.kafka.producer import KafkaProducerClient
from vms_common.logging import configure_logging, get_logger
from vms_db.session import create_engine, create_session_factory

from correlation.adapters.config_loader import load_correlation_config
from correlation.adapters.publisher import KafkaCorrelationPublisher
from correlation.adapters.topology_source import resolve_topology
from correlation.domain.topology import Topology
from correlation.settings import CorrelationSettings
from correlation.sweeper import Sweeper
from correlation.worker import CorrelationConsumer

log = get_logger(__name__)


async def _amain() -> None:
    configure_logging()
    settings = CorrelationSettings()

    try:
        config = load_correlation_config(settings.config_path)
    except (OSError, ValueError) as exc:  # missing file, bad YAML, or a ValidationError
        detail = exc.errors() if isinstance(exc, ValidationError) else str(exc)
        log.error("correlation_config_invalid", path=settings.config_path, error=detail)
        sys.exit(f"correlation: cannot start — bad config {settings.config_path}: {exc}")
    log.info(
        "correlation_config_loaded",
        path=settings.config_path,
        link_threshold=config.link_threshold,
        event_types=sorted(config.compatibility),
    )

    topology_cache = {"topology": Topology()}

    async def refresh_topology() -> None:
        while True:
            try:
                edges = await resolve_topology(
                    api_base_url=settings.api_base_url,
                    service_token=settings.service_token,
                    yaml_fallback_path=settings.topology_yaml_fallback,
                )
                topology_cache["topology"] = Topology(edges)
                log.info("topology_loaded", edges=len(edges))
            except Exception as exc:  # noqa: BLE001 - keep the last-known graph on any failure
                log.warning("topology_refresh_failed", error=str(exc))
            await asyncio.sleep(settings.topology_refresh_seconds)

    engine = create_engine(settings.db)
    session_factory = create_session_factory(engine)
    lock = asyncio.Lock()

    refresh_task = asyncio.create_task(refresh_topology())
    await asyncio.sleep(0.1)  # let the first refresh populate the graph before consuming

    def get_topology() -> Topology:
        return topology_cache["topology"]

    consumer = CorrelationConsumer(
        topic=settings.events_topic,
        group_id=settings.consumer_group,
        bootstrap_servers=settings.kafka.bootstrap_servers,
        model=EventV1,
        dlq_topic=settings.kafka.dlq_topic,
        session_factory=session_factory,
        get_topology=get_topology,
        config=config,
        lock=lock,
    )
    sweeper_task: asyncio.Task[None] | None = None
    try:
        async with (
            KafkaProducerClient(bootstrap_servers=settings.kafka.bootstrap_servers) as producer,
            consumer,
        ):
            sweeper = Sweeper(
                session_factory=session_factory,
                publisher=KafkaCorrelationPublisher(producer, topic=settings.correlations_topic),
                get_topology=get_topology,
                config=config,
                lock=lock,
                interval_s=settings.sweep_interval_seconds,
            )
            sweeper_task = asyncio.create_task(sweeper.run())
            await consumer.run()
    finally:
        background = [t for t in (refresh_task, sweeper_task) if t is not None]
        for task in background:
            task.cancel()
        # Let the cancelled tasks unwind (a sweep may be mid-query) before the pool goes away.
        await asyncio.gather(*background, return_exceptions=True)
        await engine.dispose()


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        log.info("correlation_stopped")


if __name__ == "__main__":
    main()
