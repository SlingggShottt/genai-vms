# perception

Consumes `segment.v1`, decodes + samples frames (PyAV), runs batched YOLO11
detection, per-camera ByteTrack tracking, colour/motion/zone attributes,
SigLIP2 embeddings, assembles the digital twin, and publishes
`twinready.v1` on the `vms.twin.v1` topic. (P2-D1…D5, FR-PER-01…06)

| | |
|---|---|
| **Owner** | Divyansh |
| **Port** | none in this story (grounding endpoint is J's, P4-J2) |
| **Topics** | consumes `vms.segments.v1`; produces `vms.twin.v1` |
| **GPU** | Node A, always on — one CUDA context shares YOLO11 + SigLIP2 (design_architecture.md §11.3) |
| **Config** | `VMS_PERCEPTION_*` env vars (see `settings.py`) + shared `VMS_KAFKA_*`, `VMS_STORAGE_*`, `VMS_REDIS_*` |

## Design notes

- **Domain vs adapters**: everything in `domain/` (track id formatting,
  11-colour HSV classification, motion/direction, point-in-polygon zone
  membership, adaptive-fps hysteresis, twin assembly) is pure and unit
  tested with no GPU/ML dependency. `adapters/` wraps the actual
  YOLO11/ByteTrack/SigLIP2/PyAV/OpenCV calls.
- **Cross-camera batching**: design_architecture.md §7.1 asks for batching
  *across* cameras (≤ 8 frames). This implementation batches within one
  segment's own sampled frames instead — simpler, still avoids
  one-frame-at-a-time GPU calls, but doesn't interleave concurrent
  cameras' frames into one batch. True cross-camera batching needs a
  shared batch-collector across concurrent per-segment handlers; deferred
  as a follow-up.
- **Keyframes**: perception decodes the segment independently from
  ingestion (up to 2x its 1fps rate), so its own keyframe JPEGs go under a
  `p`-prefixed filename in the same `vms-keyframes` folder ingestion
  uses — see `domain/segmenting.py`'s `build_perception_keyframe_key`
  docstring. Only frames with ≥ 1 detection are kept in the twin (empty
  frames are dropped — keeps twin documents from ballooning).
- **Tracker persistence**: `adapters/tracker.py` doesn't rely on any
  undocumented `supervision.ByteTrack` internals for persistent identity —
  it owns its own id counter and checkpoints that plus a snapshot of
  active tracks to Redis, re-associating by IoU on restore. See that
  module's docstring for exactly what does and doesn't survive a crash
  mid-track.
- **Zones**: `GET /internal/v1/zones` with a `config/zones.yaml` fallback
  (same pattern as ingestion's camera source) — only the fallback is
  exercised until P2-J4 lands. `libs/vms_common/contracts/zones.py` is a
  *proposed* day-1 contract, same treatment as `contracts/camera.py`.

## Verification status

Built with a real RTX 3050 (4 GB VRAM) available, so the whole
detect → track → attributes → embed chain was actually run against the
real libraries, not guessed — including on a real photo (ultralytics'
`bus.jpg` reference image: correctly found 1 bus + 4 people). Two real
bugs this caught that pure code review wouldn't have:

- `sv.ByteTrack.update_with_detections` does **not** return a result
  aligned 1:1 with its input — a newly-appeared object only shows up
  starting the *next* call (a one-frame confirmation lag), and the
  original design assumed positional alignment. Fixed in
  `adapters/tracker.py` (its docstring has the full story).
- Decoding a real MPEG-TS file (the container ingestion actually
  produces) gave a first frame at PTS ≈ 1.48s, not 0 — an arbitrary muxer
  offset. Without normalizing to the first frame, every `Frame.ts` in the
  twin would have been off by that amount. Fixed in `adapters/decoder.py`.

Also verified: `transformers>=5.0` needs a newer torch than 2.6.0 and
fails to import (`pyproject.toml` pins `<5.0` for that reason); ultralytics
renamed `predict(half=...)` to `predict(quantize=16)`.

Real numbers from this hardware (P2-D6): `ml/evaluation/results/p2-d6-perception-benchmark.md`.
`tests/smoke/gpu_pipeline_check.py` is the script that produced them —
rerun it to reproduce or extend.

## Run

```bash
cp ../../config/zones.example.yaml ../../config/zones.yaml
uv run --package vms-perception python -m perception.main
```

Or via Compose (profile `perception`, not yet added — lands with this
story's compose wiring).
