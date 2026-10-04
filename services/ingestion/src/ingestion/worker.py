"""Supervises one camera end to end: runs ffmpeg's segmenter, and for each
completed segment extracts keyframes, uploads both to object storage, and
publishes `segment.v1`. Reconnects with exponential backoff on failure
(FR-ING-05) and marks the next segment `gap_before=True` after a gap.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from redis.asyncio import Redis
from vms_common.contracts.camera import CameraInternal
from vms_common.contracts.segment import SegmentV1
from vms_common.kafka.producer import KafkaProducerClient
from vms_common.logging import bind_context, clear_context, get_logger
from vms_common.storage.s3 import S3Client

from ingestion.adapters.heartbeat import heartbeat_loop
from ingestion.adapters.keyframes import extract_keyframes
from ingestion.adapters.probe import StreamInfo, probe_stream
from ingestion.adapters.segmenter import (
    CompletedSegment,
    build_ffmpeg_segment_command,
    watch_for_stall,
    watch_segments,
)
from ingestion.domain.backoff import reconnect_backoff_seconds
from ingestion.domain.segmenting import (
    build_keyframe_key,
    build_keyframes_prefix,
    build_segment_id,
    build_segment_key,
)
from ingestion.metrics import segments_total, stream_reconnects_total
from ingestion.settings import IngestionSettings

log = get_logger(__name__)

SEGMENTS_TOPIC = "vms.segments.v1"


async def run_camera_worker(
    camera: CameraInternal,
    *,
    settings: IngestionSettings,
    s3: S3Client,
    producer: KafkaProducerClient,
    redis_client: Redis,
) -> None:
    """Run forever: connect, segment, upload, publish; reconnect on failure.

    Cancelled by `ingestion.main` when the camera is disabled or removed.
    """
    bind_context(camera_id=camera.code)
    status: dict[str, str] = {"value": "reconnecting"}
    heartbeat_task = asyncio.create_task(
        heartbeat_loop(redis_client, camera.code, lambda: status["value"])
    )
    attempt = 0
    gap_before = False
    try:
        while True:
            try:
                status["value"] = "online"
                await _run_once(
                    camera,
                    settings=settings,
                    s3=s3,
                    producer=producer,
                    gap_before=gap_before,
                    status=status,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                attempt += 1
                backoff = reconnect_backoff_seconds(attempt)
                status["value"] = "reconnecting"
                stream_reconnects_total.labels(camera=camera.code).inc()
                log.warning(
                    "ingestion_worker_reconnecting",
                    attempt=attempt,
                    backoff_s=backoff,
                    error=str(exc),
                )
                await asyncio.sleep(backoff)
                gap_before = True
            else:
                attempt = 0  # pragma: no cover - _run_once only returns via exception today
    finally:
        heartbeat_task.cancel()
        clear_context()


async def _run_once(
    camera: CameraInternal,
    *,
    settings: IngestionSettings,
    s3: S3Client,
    producer: KafkaProducerClient,
    gap_before: bool,
    status: dict[str, str],
) -> None:
    """One ffmpeg run. Always exits via exception (ffmpeg exit = reconnect)."""
    await asyncio.to_thread(Path(settings.work_dir).mkdir, parents=True, exist_ok=True)
    work_dir = Path(
        await asyncio.to_thread(tempfile.mkdtemp, prefix=f"{camera.code}_", dir=settings.work_dir)
    )
    segment_list_path = work_dir / "segments.list"
    stream_info = await probe_stream(camera.rtsp_url)

    cmd = build_ffmpeg_segment_command(
        rtsp_url=camera.rtsp_url,
        out_dir=work_dir,
        camera_id=camera.code,
        segment_list_path=segment_list_path,
        segment_seconds=settings.segment_seconds,
        io_timeout_seconds=settings.io_timeout_seconds,
    )
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )

    progress = {"at": time.monotonic()}  # refreshed by every completed segment
    consume_task = asyncio.create_task(
        _consume_segments(
            camera,
            work_dir,
            segment_list_path,
            stream_info=stream_info,
            settings=settings,
            s3=s3,
            producer=producer,
            gap_before=gap_before,
            status=status,
            progress=progress,
        )
    )
    wait_task = asyncio.create_task(process.wait())
    stall_task = asyncio.create_task(watch_for_stall(progress, settings.stall_timeout_seconds))

    try:
        done, pending = await asyncio.wait(
            {consume_task, wait_task, stall_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        if stall_task in done and stall_task.exception():
            raise stall_task.exception()  # the segmenter hung; the finally below kills it
        if consume_task in done and consume_task.exception():
            raise consume_task.exception()  # a segment failed to upload/publish
        raise RuntimeError(f"ffmpeg segmenter for {camera.code} exited (code {process.returncode})")
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except TimeoutError:
                process.kill()
        await asyncio.to_thread(shutil.rmtree, work_dir, ignore_errors=True)


async def _consume_segments(
    camera: CameraInternal,
    work_dir: Path,
    segment_list_path: Path,
    *,
    stream_info: StreamInfo,
    settings: IngestionSettings,
    s3: S3Client,
    producer: KafkaProducerClient,
    gap_before: bool,
    status: dict[str, str],
    progress: dict[str, float],
) -> None:
    """Consume completed segments forever (until the caller cancels this task)."""
    async for completed in watch_segments(
        segment_list_path=segment_list_path, out_dir=work_dir, worker_start=datetime.now(UTC)
    ):
        status["value"] = "online"
        progress["at"] = time.monotonic()
        await _handle_segment(
            camera,
            completed,
            stream_info=stream_info,
            settings=settings,
            s3=s3,
            producer=producer,
            gap_before=gap_before,
        )
        gap_before = False


async def _handle_segment(
    camera: CameraInternal,
    completed: CompletedSegment,
    *,
    stream_info: StreamInfo,
    settings: IngestionSettings,
    s3: S3Client,
    producer: KafkaProducerClient,
    gap_before: bool,
) -> None:
    segment_id = build_segment_id(camera.code, completed.start_ts, completed.seq)
    segment_key = build_segment_key(camera.code, completed.start_ts, segment_id)
    keyframes_prefix = build_keyframes_prefix(camera.code, completed.start_ts, completed.seq)
    keyframes_dir = completed.local_path.parent / f"{segment_id}_keyframes"

    try:
        keyframe_paths = await extract_keyframes(
            completed.local_path, keyframes_dir, fps=settings.keyframe_fps
        )

        segment_uri = f"s3://vms-segments/{segment_key}"
        await s3.upload_file(segment_uri, str(completed.local_path))

        for idx, kf_path in enumerate(keyframe_paths, start=1):
            kf_key = build_keyframe_key(keyframes_prefix, idx)
            await s3.upload_file(f"s3://vms-keyframes/{kf_key}", str(kf_path))

        message = SegmentV1(
            site_id=camera.site_id,
            camera_id=camera.code,
            segment_id=segment_id,
            start_ts=completed.start_ts,
            end_ts=completed.end_ts,
            uri=segment_uri,
            keyframes_prefix=f"s3://vms-keyframes/{keyframes_prefix}",
            fps=stream_info.fps,
            width=stream_info.width,
            height=stream_info.height,
            codec=stream_info.codec,
            gap_before=gap_before,
        )
        await producer.send(SEGMENTS_TOPIC, key=camera.code, message=message)
        segments_total.labels(camera=camera.code).inc()
        log.info("segment_ingested", segment_id=segment_id, uri=segment_uri, gap_before=gap_before)
    finally:
        await asyncio.to_thread(completed.local_path.unlink, missing_ok=True)
        await asyncio.to_thread(shutil.rmtree, keyframes_dir, ignore_errors=True)
