"""Entrypoint for the reasoning service: the job worker (phase timeline → evidence → incident
report) and the consumer that queues jobs for closed correlation groups (P5-D4, P6-D1)."""

from __future__ import annotations

import asyncio
import contextlib
from zoneinfo import ZoneInfo

from vms_common.kafka.producer import KafkaProducerClient
from vms_common.llm import LLMGateway
from vms_common.logging import configure_logging, get_logger
from vms_common.metrics import serve as serve_metrics
from vms_common.storage.s3 import S3Client
from vms_common.vqa_bank import load_vqa_bank
from vms_db.session import create_engine, create_session_factory

from reasoning.adapters.footage import Footage
from reasoning.adapters.store import ReasoningStore
from reasoning.consumers.correlations import CorrelationConsumer
from reasoning.reports.daily import ReportQueue
from reasoning.settings import ReasoningSettings
from reasoning.worker import ReasoningWorker

log = get_logger(__name__)


async def _amain() -> None:
    settings = ReasoningSettings()
    configure_logging(level=settings.log_level)
    serve_metrics(9106)  # Prometheus scrape port, design §15
    engine = create_engine(settings.db)
    sessions = create_session_factory(engine)
    store = ReasoningStore(sessions)
    s3 = S3Client(
        endpoint_url=settings.storage.endpoint_url,
        access_key=settings.storage.access_key,
        secret_key=settings.storage.secret_key,
        region=settings.storage.region,
    )
    await s3.ensure_bucket(settings.evidence_bucket)
    gateway = LLMGateway.from_settings(redis_settings=settings.redis)
    producer = KafkaProducerClient(bootstrap_servers=settings.kafka.bootstrap_servers)
    await producer.start()

    worker = ReasoningWorker(
        settings=settings,
        store=store,
        footage=Footage(store, s3),
        gateway=gateway,
        bank=load_vqa_bank(settings.vqa_bank_path),
        producer=producer,
        profile=gateway.profile,
        tz=ZoneInfo(settings.site_timezone),
        reports=ReportQueue(sessions, settings.job_lease_s),
        sessions=sessions,
    )
    tasks = [asyncio.create_task(worker.run_forever(), name="reasoning-worker")]
    consumer = CorrelationConsumer(store=store, settings=settings)
    await consumer.start()
    tasks.append(asyncio.create_task(consumer.run(), name="correlation-consumer"))
    log.info("reasoning_started", profile=gateway.profile, auto=settings.auto_enabled)
    try:
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:
            t.cancel()
        with contextlib.suppress(Exception):
            await consumer.stop()
        await producer.stop()
        await gateway.aclose()
        await engine.dispose()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
