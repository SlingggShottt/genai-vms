# ingestion

One async worker per enabled camera: pulls RTSP from MediaMTX, segments it
with ffmpeg (stream-copy, no re-encode) into 10s `.ts` files, extracts 1 fps
keyframe JPEGs per segment, uploads both to object storage, and publishes
`segment.v1` on Kafka. Reconnects with exponential backoff and marks the
next segment `gap_before=True` after a gap (FR-ING-01…05).

| | |
|---|---|
| **Owner** | Divyansh |
| **Port** | none (no HTTP surface) |
| **Topics** | produces `vms.segments.v1` |
| **Config** | `VMS_INGESTION_*` env vars (see `settings.py`) + shared `VMS_KAFKA_*`, `VMS_STORAGE_*`, `VMS_REDIS_*` |
| **Metrics** | `vms_ingest_segments_total{camera}`, `vms_stream_reconnects_total{camera}` |

## Design notes

- **Camera list**: `GET /internal/v1/cameras` with a `config/cameras.yaml`
  fallback, refreshed every `VMS_INGESTION_CAMERA_LIST_REFRESH_SECONDS`
  (default 60s). Until P1-J3 (camera management API) lands, only the YAML
  fallback is exercised — copy `config/cameras.example.yaml`.
- **Segmenting**: one long-running `ffmpeg -f segment -c copy` process per
  camera; Python watches the segment list file it writes and treats the
  moment a new entry appears as that segment's end / the next one's start
  (wall-clock, not ffmpeg's internal PTS clock). See
  `adapters/segmenter.py`'s docstring for what was actually verified
  locally, including the keyframe-interval caveat: with `-c copy`, a
  segment can only be cut on a keyframe, so actual length is
  `>= segment_seconds` if the source's GOP is longer.
- **Deviation from design_architecture.md §4**: that table mentions "RTSP
  pull (PyAV)" for ingestion; this implementation instead runs ffmpeg's own
  segment muxer directly against the RTSP URL (one process does pull +
  segment), rather than decoding with PyAV and piping frames into a
  separate muxer. Simpler, avoids a raw-frame-piping architecture, and
  still meets FR-ING-01…05. Revisit if finer-grained reconnect detection
  turns out to need frame-level access.
- **`libs/vms_common/contracts/camera.py`**: proposed day-1 per
  design_architecture.md §16 so this story could build against a fixture
  before P1-J3 exists — review together when the real API lands.

## Run

```bash
cp ../../config/cameras.example.yaml ../../config/cameras.yaml
uv run --package vms-ingestion ingestion
```

Or via Compose (profile `core`, needs `infra` + a camera source — either
`tools` (camera_sim) or a real RTSP source registered in MediaMTX):

```bash
make up PROFILE=infra,tools,core
```

## Verifying "no missing segment ids" (backlog AC)

`tests/smoke/check_no_missing_segments.py` consumes `vms.segments.v1` for a
configurable duration and reports any gap in each camera's sequence
numbers. Needs the full stack running (not run in the environment this
story was built in — no Docker daemon available there):

```bash
uv run --package vms-ingestion python tests/smoke/check_no_missing_segments.py \
  --bootstrap-servers localhost:9092 --duration-minutes 30
```
