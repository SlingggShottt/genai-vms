# camera_sim

Replays dataset videos as synchronized, looping, real-time RTSP streams
into MediaMTX (FR-ING-06, design_architecture.md §7.1). Ingestion
(`services/ingestion`) then pulls from MediaMTX exactly like it would from
a real camera — the simulator is invisible past that point.

## Run

```bash
cp ../../config/camera_sim.example.yaml ../../config/camera_sim.yaml
# edit config/camera_sim.yaml to point at real files (after ml/datasets/download/)
uv run --package vms-camera-sim camera-sim --manifest config/camera_sim.yaml
```

Or via Compose (profile `tools`, alongside `infra`):

```bash
make up PROFILE=infra,tools
```

## Manifest format

```yaml
mediamtx_url: rtsp://mediamtx:8554   # or rtsp://localhost:8554 if run on the host
cameras:
  - id: cam01                        # becomes rtsp://<mediamtx_url>/cam01
    file: ml/datasets/wildtrack/cam1.mp4
    start_offset_s: 0.0              # seek into the file before looping (sync multi-view datasets)
```

Each camera gets its own `ffmpeg -re -stream_loop -1` process, so it loops
forever at real-time rate. `start_offset_s` is what keeps a multi-view
dataset (WILDTRACK, MEVA) time-aligned: set it per camera to the point in
that camera's file that corresponds to the same real-world moment as the
other cameras' `start_offset_s`. All cameras are launched together (see
`runner.py` docstring for what "synchronized" does and doesn't guarantee).

Pass `--reencode` if a source file isn't already H.264 (default is
`-c copy`, which just remuxes — cheap but requires H.264 input).

## Source video requirements

The default `-c copy` forwards the file's H.264 stream untouched, so the file
itself must suit everything downstream:

- **No B-frames.** The live wall plays through WebRTC, and WebRTC cannot carry
  H.264 with B-frames: MediaMTX logs `WebRTC doesn't support H264 streams with
  B-frames`, closes the viewer's session straight away, and the tile stays
  black while the stream is otherwise fine (recording and perception still
  work). Most downloaded or phone footage is High profile *with* B-frames.
  `--reencode` does **not** fix this (it uses libx264's defaults, which use
  B-frames) — re-encode the file once instead.
- **A keyframe at least every ~2 s.** Ingestion cuts 10 s segments with
  `-c copy`, which can only cut on a keyframe; a 5 s keyframe interval gives
  uneven 10–11 s segments (the first can be longer still).
- Keep it modest (720p is plenty): perception decodes it on the CPU and runs
  YOLO11 on a 4 GB GPU.

Check a clip (`has_b_frames=1` or `profile=High` means it needs re-encoding),
then re-encode it. The `camera-sim` image has both tools, so no host ffmpeg is
needed — run from the repo root after `docker compose … build camera-sim`
(or use `ffmpeg`/`ffprobe` directly if installed):

```bash
IMG=genai-vms-camera-sim; DIR=ml/datasets/demo     # image name = <compose project>-camera-sim
docker run --rm -v "$PWD/$DIR:/w" --entrypoint ffprobe $IMG -v error \
  -select_streams v:0 -show_entries stream=codec_name,profile,has_b_frames -of default=nw=1 /w/in.mp4

docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/$DIR:/w" --entrypoint ffmpeg $IMG -y \
  -i /w/in.mp4 -vf scale=1280:-2 -c:v libx264 -profile:v baseline -bf 0 -g 30 -preset veryfast \
  -pix_fmt yuv420p -an /w/cam01.mp4          # -g = your frame rate → one keyframe per second
# (--user keeps the output owned by you; without it docker writes a root-owned file)
```

The result should report `profile=Constrained Baseline` and `has_b_frames=0`.
Both commands were run against the image as written. Then point
`config/camera_sim.yaml` at it.

## Publishing a real camera or phone instead

camera_sim only replays dataset files. A live camera or phone doesn't need
this tool at all — it pushes straight to MediaMTX:

1. Install an RTSP-publishing app (Android: **IP Webcam**; iOS/Android:
   **Larix Broadcaster**).
2. Point it at `rtsp://<mediamtx-host>:8554/<camera-id>` (e.g.
   `rtsp://192.168.1.20:8554/cam05` — use the machine running MediaMTX's
   LAN IP, not `localhost`, since the phone is a separate device).
3. Register `cam05` the same way as any other camera (Settings → Cameras,
   P1-J3) — the RTSP path *is* the camera id, MediaMTX doesn't care whether
   the publisher is camera_sim, a real IP camera, or a phone.
