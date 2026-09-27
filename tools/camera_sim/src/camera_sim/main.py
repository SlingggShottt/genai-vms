"""CLI entrypoint: `uv run --package vms-camera-sim camera-sim`.

Reads a manifest (default `config/camera_sim.yaml`) and replays each
camera's video file as a real-time RTSP stream to MediaMTX until stopped
(Ctrl+C). See README.md for the manifest format and a phone-camera
alternative that doesn't need this tool at all.
"""

from __future__ import annotations

import argparse
import asyncio

from vms_common.logging import configure_logging, get_logger

from camera_sim.manifest import load_manifest
from camera_sim.runner import run_all

log = get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay dataset videos as live RTSP cameras.")
    parser.add_argument(
        "--manifest",
        default="config/camera_sim.yaml",
        help="path to the camera manifest (default: config/camera_sim.yaml)",
    )
    parser.add_argument(
        "--reencode",
        action="store_true",
        help="transcode to H.264 instead of stream-copying (use if source files aren't H.264)",
    )
    return parser.parse_args(argv)


async def _amain(argv: list[str] | None = None) -> None:
    configure_logging()
    args = _parse_args(argv)
    manifest = load_manifest(args.manifest)
    log.info(
        "camera_sim_manifest_loaded",
        cameras=[c.id for c in manifest.cameras],
        mediamtx_url=manifest.mediamtx_url,
    )
    await run_all(manifest.cameras, mediamtx_url=manifest.mediamtx_url, reencode=args.reencode)


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        log.info("camera_sim_stopped")


if __name__ == "__main__":
    main()
