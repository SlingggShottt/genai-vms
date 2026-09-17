# Track D — Divyansh Pankaj Mishra (1RV25MC028)

**Total: 161 story points** (Jatin: 161). Full acceptance criteria are in `docs/backlog.md`; this file is your map of what you own, what you hand over and what you wait on.

## What you own

| Area | Paths |
|---|---|
| Shared runtime | `libs/vms_common/{kafka,storage,llm,config.py,logging.py,metrics.py}` · contracts co-owned |
| Media & perception plane | `services/ingestion`, `services/perception` (except `grounding/`), `tools/camera_sim` |
| Event detection | `services/events`, `config/rules.yaml` |
| GenAI foundation | LLM gateway, `config/models.yaml`, GPU lease, prompts for your tasks |
| Search (text) | `services/retrieval/search/text`, `frontend/src/features/search` |
| Reasoning | `services/reasoning/{orchestrator,synthesis}`, TG adapter (`ml/training/tg`) |
| Assistant | `services/retrieval/assistant`, `frontend/src/features/assistant` |
| Infra & ops | `deploy/compose` infra profile, `deploy/k8s/base/{infra,obs}`, latency & resilience evaluation |

**Résumé-level skills covered:** real-time video pipelines (RTSP, FFmpeg, Kafka), multi-object tracking, vision embeddings, LLM gateway design, reasoning-based retrieval, QLoRA VLM fine-tuning, structured LLM generation with validation, tool-using RAG agents with streaming, React UI, Kubernetes operators + GPU scheduling, Prometheus/Grafana.

---

## Phase 1 — Foundation & live ingestion · 24 pts · weeks 1–2

| Story | Title | Pts |
|---|---|---|
| P1-D1 | Monorepo scaffold | 3 |
| P1-D2 | Shared runtime library v1 (config, logging, Kafka, S3, `segment.v1`) | 5 |
| P1-D3 | Infrastructure Compose | 3 |
| P1-D4 | Camera simulator | 3 |
| P1-D5 | Ingestion service | 8 |
| P1-D6 | Dataset acquisition scripts | 2 |

- **You provide:** `segment.v1` + fixture; MediaMTX path naming (`rtsp://mediamtx:8554/cam01`, WebRTC/HLS URLs); running `infra` profile.
- **You consume:** `/internal/v1/cameras` (Jatin) → use `config/cameras.yaml` fallback until P1-J3 merges.
- **Do first (day 1–2):** P1-D1 → P1-D3 so Jatin can run Postgres/MediaMTX; then contracts in P1-D2.
- **Phase II demo contribution:** simulator streaming 6 cameras, segments landing in object storage, Kafka topic visibly filling.

## Phase 2 — Perception & digital twin · 23 pts · weeks 3–4

| Story | Title | Pts |
|---|---|---|
| P2-D1 | Perception worker & batched detection | 5 |
| P2-D2 | Persistent multi-camera tracking | 5 |
| P2-D3 | Attributes, motion & zones | 3 |
| P2-D4 | Digital twin writer | 3 |
| P2-D5 | SigLIP 2 embeddings | 5 |
| P2-D6 | Perception benchmark on 4 GB | 2 |

- **You provide:** `twin.v1`, `twinready.v1`, `.npz` layout + fixtures (freeze on day 1 — Jatin's indexer and overlay depend on them).
- **You consume:** zones internal API (Jatin, P2-J4) → YAML fallback.
- **Watch out:** VRAM. Keep YOLO + SigLIP in one process (one CUDA context). Commit measured numbers from P2-D6.

## Phase 3 — Events & GenAI gateway · 23 pts · weeks 5–6

| Story | Title | Pts |
|---|---|---|
| P3-D1 | Events service & core rules | 5 |
| P3-D2 | Advanced rules (abandoned object, running) | 5 |
| P3-D3 | LLM gateway & model registry (+ GPU lease, cache, `FakeGateway`) | 5 |
| P3-D4 | VLM verification gate | 3 |
| P3-D5 | Phase annotation kit (guideline, Label Studio config, clip extraction, export) | 5 |

- **You provide:** `event.v1` + fixtures; `LLMGateway` interface, `models.yaml`, `FakeGateway` (Jatin uses it for JIT, evidence and daily narrative); phase export schema.
- **You consume:** `correlation.v1` fixture (for planning P5 only).
- **Hand-off to support track:** annotation kit ready by end of week 5 so Kuldeep & Pankaj start labelling in week 6. Get the guide's sign-off on the phase taxonomy (design §8.2) in week 5.

## Phase 4 — Multimodal search (text pipeline) · 23 pts · weeks 7–8

| Story | Title | Pts |
|---|---|---|
| P4-D1 | Retrieval service & query decomposition | 5 |
| P4-D2 | Coarse hybrid retrieval | 8 |
| P4-D3 | LLM reasoning rerank & traces | 5 |
| P4-D4 | Search UI | 5 |

- **You provide:** `queryplan.v1`, `candidate.v1`, search response schema + fixtures.
- **You consume:** grounding + image-search response fixtures (Jatin) for the UI; `knowledge` collection filled with event captions (P4-J4) — use fixture points until then.
- **Evaluation link:** Jatin's harness (P4-J6) calls your `/search`; keep per-stage timings in the response.

## Phase 5 — Phase-aware reasoning (TG) · 22 pts · weeks 9–10

| Story | Title | Pts |
|---|---|---|
| P5-D1 | TG dataset builder | 3 |
| P5-D2 | TG adapter fine-tuning (Kaggle/Colab, Unsloth QLoRA) | 8 |
| P5-D3 | TG evaluation (mIoU, baselines, error analysis) | 3 |
| P5-D4 | Reasoning orchestrator (queue, clips, TG, fallbacks) | 5 |
| P5-D5 | Adapter serving (`hf_local`, adapter hot-swap) | 3 |

- **You provide:** `phasetimeline.v1`, `incident.v1`, `incidentready.v1` + fixtures (freeze day 1; Jatin builds the incident UI against them in P6).
- **You consume:** `evidence.v1` fixture (Jatin, P5-J4); phase labels from the support track.
- **Risk plan:** if fewer than 150 labelled clips exist at week 9, start training on what exists and keep the zero-shot path as the default in the orchestrator; retrain at end of week 10.
- **Tip:** start P5-D4 and P5-D5 on day 1 with the base model while the first training run is going on Kaggle.

## Phase 6 — Incident synthesis & assistant · 23 pts · weeks 11–12

| Story | Title | Pts |
|---|---|---|
| P6-D1 | Incident report synthesis (hierarchical, citations, retry) | 8 |
| P6-D2 | RAG assistant agent & SSE streaming | 8 |
| P6-D3 | Conversation memory | 2 |
| P6-D4 | Assistant UI | 5 |

- **You provide:** incidents via `incidentready.v1`; assistant SSE event format.
- **You consume:** events/incidents/timeline query endpoints (Jatin, P6-J3) — freeze their OpenAPI on day 1; daily report lookup endpoint.

## Phase 7 — Kubernetes infra, observability, latency · 23 pts · weeks 13–14

| Story | Title | Pts |
|---|---|---|
| P7-D1 | Kubernetes infra layer (Strimzi, CloudNativePG, Qdrant, Redis, storage, MediaMTX) | 5 |
| P7-D2 | GPU scheduling in Kubernetes (+ ExternalName fallback) | 5 |
| P7-D3 | Observability (metrics, Prometheus, Grafana dashboards) | 5 |
| P7-D4 | Latency & throughput evaluation | 5 |
| P7-D5 | Resilience tests (chaos restarts, DLQ replay, degradation) | 3 |

- **You provide:** `deploy/k8s/base/infra/SERVICES.md` (names/ports) on day 1 for Jatin's app manifests.
- **Final report sections you write:** pipeline architecture, perception benchmarks, TG results, search pipeline design, latency results, Kubernetes/GPU deployment.

---

## Your weekly rhythm

- **Mon:** read both tracks' stories for the week; update fixtures if a contract gained an optional field.
- **Daily:** small PRs to `main`; Jatin reviews. Review his PRs within 24 h.
- **Fri:** 20-min joint demo on `make up`; update `backlog.md` checkboxes; note blockers for Kuldeep/Pankaj.
