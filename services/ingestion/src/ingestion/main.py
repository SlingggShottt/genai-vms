"""Entrypoint for the ingestion service: one async worker per enabled
camera (FR-ING-01), camera list refreshed periodically (FR-CAM-05).
"""

from __future__ import annotations

import asyncio

from vms_common.kafka.producer import KafkaProducerClient
from vms_common.logging import configure_logging, get_logger
from vms_common.metrics import serve as serve_metrics
from vms_common.redis import get_redis_client
from vms_common.storage.s3 import S3Client

from ingestion.adapters.camera_source import resolve_cameras
from ingestion.settings import IngestionSettings
from ingestion.worker import run_camera_worker

log = get_logger(__name__)


async def _amain() -> None:
    configure_logging()
    serve_metrics(9101)  # Prometheus scrape port, design §15
    settings = IngestionSettings()

    s3 = S3Client(
        endpoint_url=settings.storage.endpoint_url,
        access_key=settings.storage.access_key,
        secret_key=settings.storage.secret_key,
        region=settings.storage.region,
    )
    for bucket in ("vms-segments", "vms-keyframes"):
        await s3.ensure_bucket(bucket)

    redis_client = get_redis_client(settings.redis)

    producer = KafkaProducerClient(bootstrap_servers=settings.kafka.bootstrap_servers)
    await producer.start()

    workers: dict[str, asyncio.Task] = {}
    try:
        while True:
            cameras = await resolve_cameras(
                api_base_url=settings.api_base_url,
                service_token=settings.service_token,
                yaml_fallback_path=settings.cameras_yaml_fallback,
            )
            enabled = {c.code: c for c in cameras if c.enabled}

            for code in list(workers):
                if code not in enabled:
                    log.info("camera_removed_stopping_worker", camera_id=code)
                    workers.pop(code).cancel()

            for code, camera in enabled.items():
                if code not in workers:
                    log.info("camera_added_starting_worker", camera_id=code)
                    workers[code] = asyncio.create_task(
                        run_camera_worker(
                            camera,
                            settings=settings,
                            s3=s3,
                            producer=producer,
                            redis_client=redis_client,
                        )
                    )

            await asyncio.sleep(settings.camera_list_refresh_seconds)
    finally:
        for task in workers.values():
            task.cancel()
        await producer.stop()
        await redis_client.aclose()


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        log.info("ingestion_stopped")


if __name__ == "__main__":
    main()
