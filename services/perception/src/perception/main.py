"""Entrypoint for the perception service: one Kafka consumer processing
`segment.v1` from every camera, one YOLO11 + SigLIP2 model pair shared
across all of them (design_architecture.md §11.3: "Keep YOLO + SigLIP in
one process — one CUDA context").
"""

from __future__ import annotations

import asyncio

from vms_common.config import LLMSettings
from vms_common.contracts.segment import SegmentV1
from vms_common.gpu_metrics import start_gpu_metrics
from vms_common.kafka.producer import KafkaProducerClient
from vms_common.logging import configure_logging, get_logger
from vms_common.metrics import serve as serve_metrics
from vms_common.redis import get_redis_client
from vms_common.storage.s3 import S3Client

from perception.adapters.detector import YoloDetector
from perception.adapters.embedder import SiglipEmbedder
from perception.adapters.zones_source import resolve_zones
from perception.settings import PerceptionSettings
from perception.worker import PerceptionConsumer

log = get_logger(__name__)

SEGMENTS_TOPIC = "vms.segments.v1"
PERCEPTION_VERSION = "yolo11s-bytetrack-siglip2b@0.1.0"
ZONES_REFRESH_STARTUP_GRACE_S = 0.1  # let the first refresh populate zones_cache before consuming


async def _amain() -> None:
    configure_logging()
    serve_metrics(9102)  # Prometheus scrape port, design §15
    settings = PerceptionSettings()
    gpu_reporter = start_gpu_metrics(LLMSettings().lease_node)  # vms_gpu_memory_bytes

    s3 = S3Client(
        endpoint_url=settings.storage.endpoint_url,
        access_key=settings.storage.access_key,
        secret_key=settings.storage.secret_key,
        region=settings.storage.region,
    )
    for bucket in ("vms-twins", "vms-crops", "vms-keyframes"):
        await s3.ensure_bucket(bucket)

    redis_client = get_redis_client(settings.redis)
    producer = KafkaProducerClient(bootstrap_servers=settings.kafka.bootstrap_servers)
    await producer.start()

    log.info("loading_models", model=settings.model_name, device=settings.device)
    detector = YoloDetector(
        model_name=settings.model_name,
        device=settings.device,
        classes=settings.detect_classes,
        confidence_threshold=settings.confidence_threshold,
    )
    embedder = SiglipEmbedder(model_name=settings.embedding_model_name, device=settings.device)

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

    consumer = PerceptionConsumer(
        topic=SEGMENTS_TOPIC,
        group_id="perception",
        bootstrap_servers=settings.kafka.bootstrap_servers,
        model=SegmentV1,
        dlq_topic=settings.kafka.dlq_topic,
        settings=settings,
        s3=s3,
        producer=producer,
        redis_client=redis_client,
        detector=detector,
        embedder=embedder,
        get_zones=lambda: zones_cache["zones"],
        perception_version=PERCEPTION_VERSION,
    )

    try:
        async with consumer:
            await consumer.run()
    finally:
        refresh_task.cancel()
        if gpu_reporter is not None:
            gpu_reporter.cancel()
        await producer.stop()
        await redis_client.aclose()


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        log.info("perception_stopped")


if __name__ == "__main__":
    main()
