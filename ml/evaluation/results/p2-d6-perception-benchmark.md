# P2-D6 — Perception benchmark on 4 GB

**Measured 27 Sep 2026** on the actual target hardware class: NVIDIA GeForce
RTX 3050 Laptop GPU, 4096 MiB VRAM, driver 581.83 / CUDA 13.0, via
`torch==2.6.0+cu124`.

## What this covers vs. what it doesn't

This is **model-level** benchmarking (`services/perception/tests/smoke/
gpu_pipeline_check.py`): both models loaded in one process, real detection
+ tracking + attributes + embedding on a real image, plus synthetic-load
timing. It does **not** cover the full backlog AC ("2/4/6 simulated
cameras for 20 min... consumer lag") — that needs the live stack (Kafka,
camera_sim, ingestion, perception all running together), which this
environment doesn't have (no Docker daemon). Numbers below are real,
model-level measurements to ground the design, not the end-to-end
multi-camera run the story ultimately asks for.

## Results

| Stage | Measurement |
|---|---|
| YOLO11s load | 38 MB VRAM |
| + SigLIP2 base load | 804 MB VRAM total |
| YOLO11s warm inference, batch of 8 @ 1080p | 37.4 ms mean (36.2 ms min) |
| SigLIP2 warm inference, batch of 8 @ 224×224 | 34.7 ms mean (34.1 ms min) |
| Peak VRAM, both models loaded + batched inference | 966 MB |

Real detection quality check (not synthetic noise): ultralytics' own
`bus.jpg` reference image — YOLO11s correctly found 1 bus (conf 0.94) and
4 people (conf 0.86–0.88, one partly-occluded person at 0.57), matching
that image's known content exactly.

## What this means for the 4 GB budget

Both models together use well under 1 GB at these batch sizes — the
perception plane alone is nowhere near the 4 GB ceiling design_architecture.md
§11.3 budgets for it (~1.5–2 GB planning estimate; this measured ~0.8–1 GB
model-loaded, before decode/tracking overhead). The real pressure on 4 GB
comes from the **GenAI plane** (Ollama/hf_local models, §11.3's node B
budget), not perception — consistent with the two-node demo topology
already being the documented default.

## Not yet measured (needs live infra)

- Actual segment→twin pipeline latency (decode + detect + track + attrs +
  embed + S3 upload, end to end per 10s segment)
- Consumer lag / adaptive-sampling behavior under real multi-camera load
- 2 vs 4 vs 6 concurrent camera scaling
- Sustained 20-minute run stability

Re-run `gpu_pipeline_check.py` plus a proper multi-camera load test once
`infra` + `tools` (camera_sim) + `core` (ingestion) + `perception` are all
up together, and replace this file's "not yet measured" section with real
numbers.
