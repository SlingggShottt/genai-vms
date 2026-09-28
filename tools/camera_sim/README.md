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
