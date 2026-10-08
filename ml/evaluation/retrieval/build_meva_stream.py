"""Builds the MEVA example stream for the retrieval benchmark and its ground truth.

    uv run --package vms-common python ml/evaluation/retrieval/build_meva_stream.py [--register]

The MEVA "examples" set is 121 short clips (5-38 s) of 36 labelled activities, each clip named
`exNNN-<activity>.mp4`. This joins them into ONE stream, `ml/datasets/raw/meva/sim/meva-ex.mp4`, so
the normal pipeline (camera simulator -> ingestion -> perception -> indexer) can record it as a
single camera, and writes `meva_ex_manifest.json`: where every clip sits on the stream's timeline.
The benchmark (`meva_benchmark.py`) turns that into "which windows of footage are relevant to a
query" without any human labelling.

The stream is: a black leader (ingestion joins a stream late and loses its first seconds), then
every clip followed by a black gap (so a 10 s window rarely holds two clips). Everything is
re-encoded to 1280x720, 15 fps, H.264 baseline, no B-frames, a keyframe every second (what the
simulator needs, tools/camera_sim/README.md), in parts that are then joined without re-encoding.
ffmpeg comes from the `genai-vms-camera-sim` image (no host ffmpeg). MEVA video is research-only:
it stays under ml/datasets/raw/ (gitignored); only the manifest is committed.

`--register` also adds the camera `meva-ex` (disabled) to config/cameras.yaml and the API, which
the benchmark runner needs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CLIPS = ROOT / "ml/datasets/raw/meva/examples/videos"
SIM_DIR = ROOT / "ml/datasets/raw/meva/sim"
MANIFEST = ROOT / "ml/evaluation/retrieval/meva_ex_manifest.json"
SIM_MANIFEST = ROOT / "ml/datasets/raw/meva/camera_sim.meva-ex.yaml"
IMAGE = "genai-vms-camera-sim"
CAMERA = "meva-ex"
LEADER_S = 45
GAP_S = 5
FPS = 15

ENCODE = (
    "-c:v libx264 -profile:v baseline -bf 0 -g 15 -keyint_min 15 -sc_threshold 0 "
    "-preset veryfast -crf 26 -pix_fmt yuv420p -an"
)
FIT = (
    "scale=1280:720:force_original_aspect_ratio=decrease,"
    "pad=1280:720:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=15,format=yuv420p"
)

BLACK = f"color=c=black:s=1280x720:r={FPS}"

# Runs inside the container: /in = the clips, /work = scratch + output.
INNER = f"""#!/bin/bash
set -euo pipefail
cd /work
ffmpeg -nostdin -v error -y -f lavfi -i {BLACK} -t {LEADER_S} {ENCODE} leader.mp4
ffmpeg -nostdin -v error -y -f lavfi -i {BLACK} -t {GAP_S} {ENCODE} gap.mp4
ls /in/*.mp4 | sort | xargs -P 4 -I{{}} bash -c \\
  'b=$(basename {{}} .mp4); ffmpeg -nostdin -v error -y -i {{}} -vf "{FIT}" {ENCODE} "part_$b.mp4"'
: > list.txt
echo "file 'leader.mp4'" >> list.txt
for f in $(ls /in/*.mp4 | sort); do
  b=$(basename "$f" .mp4)
  echo "file 'part_$b.mp4'" >> list.txt
  echo "file 'gap.mp4'" >> list.txt
done
ffmpeg -nostdin -v error -y -f concat -safe 0 -i list.txt -c copy meva-ex.mp4
for f in leader.mp4 gap.mp4 part_*.mp4 meva-ex.mp4; do
  echo "$f $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")"
done > durations.txt
ffmpeg -nostdin -v error -i meva-ex.mp4 -f null - 2> decode_errors.txt || true
"""


def docker(args: list[str]) -> list[str]:
    """`docker ...`, through `sg docker` when the shell does not have the docker group yet."""
    ok = subprocess.run(["docker", "info"], capture_output=True).returncode == 0  # noqa: S607
    cmd = ["docker", *args]
    return cmd if ok else ["sg", "docker", "-c", shlex.join(cmd)]


def build() -> dict:
    clips = sorted(CLIPS.glob("ex*.mp4"))
    if not clips:
        sys.exit(f"no clips in {CLIPS} (download MEVA examples first)")
    SIM_DIR.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="meva-ex-", dir=SIM_DIR))
    script = work / "inner.sh"
    script.write_text(INNER)
    run = docker(
        [
            "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}",
            "-v", f"{CLIPS}:/in:ro", "-v", f"{work}:/work",
            "--entrypoint", "bash", IMAGE, "/work/inner.sh",
        ]
    )  # fmt: skip
    print("encoding 121 clips (a few minutes)...", flush=True)
    subprocess.run(run, check=True)  # noqa: S603 - fixed argv built above, no outside input

    durations = {}
    for line in (work / "durations.txt").read_text().splitlines():
        name, value = line.split()
        durations[name] = float(value)
    errors = (work / "decode_errors.txt").read_text().strip()
    if errors:
        print("decode warnings from the joined file:\n" + errors[:600])

    t = durations["leader.mp4"]
    gap = durations["gap.mp4"]
    entries = []
    for clip in clips:
        stem = clip.stem
        m = re.fullmatch(r"ex(\d+)-(.+)", stem)
        if not m:
            sys.exit(f"unexpected clip name {clip.name}")
        d = durations[f"part_{stem}.mp4"]
        entries.append(
            {"clip": stem, "activity": m.group(2), "start_s": round(t, 3), "end_s": round(t + d, 3)}
        )
        t += d + gap
    total = durations["meva-ex.mp4"]
    print(f"timeline sum {t:.1f} s, file {total:.1f} s (difference {t - total:+.2f} s)")
    if abs(t - total) > 2:
        sys.exit("the joined file's length does not match the clip timeline; do not use it")

    (work / "meva-ex.mp4").replace(SIM_DIR / "meva-ex.mp4")
    for f in work.iterdir():
        f.unlink()
    work.rmdir()

    manifest = {
        "stream": "meva-ex.mp4",
        "camera": CAMERA,
        "leader_s": LEADER_S,
        "gap_s": GAP_S,
        "fps": FPS,
        "duration_s": round(total, 3),
        "source": "MEVA public examples (mevadata-public-01/examples), research-only",
        "labels": "the clip names",
        "clips": entries,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=1) + "\n")
    SIM_MANIFEST.write_text(
        "mediamtx_url: rtsp://mediamtx:8554\n\ncameras:\n"
        f"  - id: {CAMERA}\n    file: ml/datasets/raw/meva/sim/meva-ex.mp4\n"
        "    start_offset_s: 0.0\n"
    )
    print(f"wrote {MANIFEST.relative_to(ROOT)} ({len(entries)} clips) and {SIM_MANIFEST.name}")
    return manifest


def register() -> None:
    """Add `meva-ex` (disabled) to config/cameras.yaml and the API."""
    path = ROOT / "config/cameras.yaml"
    text = path.read_text()
    if f"id: {CAMERA}" not in text:
        text = (
            text.rstrip("\n")
            + f"""
  # Retrieval benchmark stream (ml/evaluation/retrieval); enabled only while it is recorded.
  - id: {CAMERA}
    code: {CAMERA}
    name: MEVA examples (retrieval benchmark)
    rtsp_url: rtsp://mediamtx:8554/{CAMERA}
    site_id: meva-bench
    location_label: Benchmark stream
    enabled: false
"""
        )
        path.write_text(text)
        print("added to config/cameras.yaml")
    import httpx
    from dotenv import dotenv_values

    env = dotenv_values(ROOT / ".env")
    c = httpx.Client(base_url="http://localhost:8000/api/v1", timeout=20)
    r = c.post(
        "/auth/login", json={"email": env["VMS_ADMIN_EMAIL"], "password": env["VMS_ADMIN_PASSWORD"]}
    )
    r.raise_for_status()
    c.headers["Authorization"] = "Bearer " + r.json()["access_token"]
    have = {x["code"] for x in c.get("/cameras", params={"limit": 100}).json()["items"]}
    if CAMERA in have:
        print("camera already registered")
        return
    r = c.post(
        "/cameras",
        json={
            "code": CAMERA, "name": "MEVA examples (retrieval benchmark)",
            "rtsp_url": f"rtsp://mediamtx:8554/{CAMERA}", "site_id": "meva-bench",
            "location_label": "Benchmark stream", "enabled": False,
        },
    )  # fmt: skip
    r.raise_for_status()
    print("registered in the API (disabled)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--register", action="store_true", help="also add the camera meva-ex (disabled)"
    )
    ap.add_argument("--skip-build", action="store_true", help="only register")
    args = ap.parse_args()
    if not args.skip_build:
        build()
    if args.register:
        register()
