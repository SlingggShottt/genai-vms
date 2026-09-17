# Product Backlog

| | |
|---|---|
| **Version** | 0.1 — 17 Sep 2026 |
| **Cadence** | 7 phases × 2 weeks. Week 1 starts **Mon 21 Sep 2026** (tentative; adjust to review dates) |
| **Estimation** | Fibonacci story points (1, 2, 3, 5, 8). ≈ 1 point ≈ half a focused day for one builder |
| **Split** | Divyansh **161 pts** · Jatin **161 pts** · every phase within ±1 pt |
| **Priority** | Must / Should / Could (MoSCoW) |

## How to use this backlog

- Story ids: `P<phase>-<D|J><n>`. `D` = Divyansh, `J` = Jatin.
- **Day 1 of every phase:** 1-hour contract freeze (see `design_architecture.md §16`). Contracts + fixtures merged before stories start.
- Stories inside a phase are independent across tracks; cross-track needs are satisfied by fixtures.
- **Definition of Done (every story):** acceptance criteria met · unit tests for domain logic · lint/CI green · reviewed by the other builder · docs updated (service README / relevant doc) · demoable on `make up`.
- Moving a story between builders requires swapping stories of equal points so the split stays balanced.

## Epics

| Epic | Name | Phases | PRD features |
|---|---|---|---|
| E01 | Platform foundation | 1 | — |
| E02 | Live ingestion & media | 1 | F-03, F-04 |
| E03 | Access & configuration | 1, 2, 3 | F-01, F-02, F-09 |
| E04 | Dashboard shell & live wall | 1 | F-04 |
| E05 | Perception & digital twin | 2 | F-05 |
| E06 | Indexing & playback | 2 | F-06, F-07 |
| E07 | Event detection | 3 | F-08 |
| E08 | Correlation & alerts | 3 | F-10, F-11 |
| E09 | GenAI foundation | 3 | F-12 |
| E10 | Datasets & annotation | 1, 3, 5 | F-16 |
| E11 | Multimodal search | 4 | F-13, F-14, F-15 |
| E12 | Phase-aware event reasoning | 5 | F-16 |
| E13 | Incident summarization | 6 | F-17 |
| E14 | RAG assistant | 6 | F-18 |
| E15 | Daily security reports | 6 | F-19 |
| E16 | Investigation timeline | 6 | F-20 |
| E17 | Deployment & operations | 1, 7 | F-21, F-22, F-23 |
| E18 | Evaluation | 4, 5, 7 | F-24 |

## Points overview

| Phase | Dates (tentative) | Theme | Divyansh | Jatin |
|---|---|---|---|---|
| 1 | 21 Sep – 4 Oct | Foundation & live ingestion (**Phase II review**) | 24 | 24 |
| 2 | 5 – 18 Oct | Perception, digital twin, indexing & playback | 23 | 23 |
| 3 | 19 Oct – 1 Nov | Events, correlation, alerts, GenAI gateway, annotation kickoff | 23 | 23 |
| 4 | 2 – 15 Nov | Multimodal search | 23 | 23 |
| 5 | 16 – 29 Nov | Phase-aware event reasoning (fine-tuning) | 22 | 22 |
| 6 | 30 Nov – 13 Dec | Incident reports, assistant, daily reports, investigation | 23 | 23 |
| 7 | 14 – 27 Dec | Kubernetes, cloud, observability, evaluation, hardening | 23 | 23 |
| **Total** | | | **161** | **161** |

---

# Phase 1 — Foundation & live ingestion (weeks 1–2)

**Goal / Phase II demo:** log in → see 4–6 live camera tiles (simulated from datasets) → segments visibly arriving in Kafka (kafka-ui) and object storage.

**Contracts frozen day 1:** `segment.v1`, camera internal API, MediaMTX path naming.

## Divyansh — 24 pts

### P1-D1 · Monorepo scaffold — 3 pts · Must · E01
- [ ] uv workspace with `libs/vms_common`, `libs/vms_db`, and empty service packages following `style_guide.md §A.1` layout.
- [ ] Root `Makefile`: `make setup`, `make up PROFILE=…`, `make down`, `make test`, `make lint`.
- [ ] Ruff + pytest config shared; pre-commit with ruff, nbstripout, gitleaks.
- [ ] `CODEOWNERS` created from `design_architecture.md §3`.

### P1-D2 · Shared runtime library v1 — 5 pts · Must · E01 · NFR-REL-01, NFR-OBS-01
- [ ] `vms_common.config` (pydantic-settings), `logging` (structlog JSON with context binding), `ids` (uuid7), `metrics` helpers.
- [ ] `vms_common.kafka`: async producer, consumer base class with validate → handle → commit, retry backoff, DLQ publish.
- [ ] `vms_common.storage`: S3 client (put/get/stream/presign), URI parse/build helpers.
- [ ] `contracts/segment.py` (`SegmentV1`) + fixture + round-trip test.
- [ ] Integration test with testcontainers Kafka: message produced → consumed → committed; poison message → DLQ.

### P1-D3 · Infrastructure Compose — 3 pts · Must · E17
- [ ] `deploy/compose/docker-compose.yml` with profile `infra`: Kafka (KRaft), kafka-ui, Postgres, Qdrant, Redis, object storage (buckets auto-created), MediaMTX.
- [ ] Healthchecks on every container; `.env.example` documented.
- [ ] Topic bootstrap script creates topics from `design_architecture.md §5.2`.
- [ ] `nvidia-smi` works inside a test GPU container on both laptops (documented in README troubleshooting).

### P1-D4 · Camera simulator — 3 pts · Must · E02 · FR-ING-06
- [ ] `tools/camera_sim` reads a YAML (camera id → video file, start offset) and publishes looping RTSP streams to MediaMTX at real-time rate.
- [ ] Synchronized start for multi-view datasets (WILDTRACK/MEVA offsets honoured).
- [ ] Compose service in profile `tools`; doc for publishing a phone camera as a live source.

### P1-D5 · Ingestion service — 8 pts · Must · E02 · FR-ING-01…05
- [ ] One async worker per enabled camera, camera list from `GET /internal/v1/cameras` (fallback `config/cameras.yaml`), refreshed every 60 s.
- [ ] FFmpeg segmenter writes 10 s MPEG-TS segments without re-encode; each uploaded to `vms-segments` with the key layout in design §6.3.
- [ ] Keyframes at 1 fps uploaded to `vms-keyframes`.
- [ ] `segment.v1` published per segment with correct UTC start/end; `gap_before=true` after reconnects.
- [ ] Reconnect with exponential backoff ≤ 30 s; camera status heartbeat to Redis `camera:status:<id>` every 5 s.
- [ ] Metrics `vms_ingest_segments_total`, `vms_stream_reconnects_total`.
- [ ] Runs 6 simulated cameras for 30 min with no missing segment ids (test script).

### P1-D6 · Dataset acquisition scripts — 2 pts · Must · E10
- [ ] `ml/datasets/download/` scripts + manifests for scoped subsets: WILDTRACK (full), MEVA (≤ 60 GB subset with ≥ 4 synchronized cameras), UCF-Crime (8 classes), ShanghaiTech Campus.
- [ ] `ml/datasets/README.md` lists licence/usage terms and disk sizes.

## Jatin — 24 pts

### P1-J1 · API service skeleton & database — 5 pts · Must · E01, E03
- [ ] FastAPI app factory, router layout, error envelope (`style_guide.md §A.5`), request-id middleware, `/health`, `/ready`, `/metrics`.
- [ ] `libs/vms_db`: async engine/session, base model, Alembic configured with per-domain schemas.
- [ ] Migration 0001: `core.users`, `core.refresh_tokens`, `core.cameras`, `core.audit_log`.
- [ ] Integration tests with testcontainers Postgres.

### P1-J2 · Authentication & RBAC — 5 pts · Must · E03 · FR-AUTH-01…05
- [ ] Login returns access (15 min) + refresh (7 d) JWT; refresh rotation; logout revokes.
- [ ] Argon2id hashing; seed admin from env on first start.
- [ ] `require_role()` dependency; service-token dependency for `/internal/*`.
- [ ] Users CRUD (admin only); audit log entries for login and user changes.
- [ ] Role × endpoint test matrix generated from the router table.

### P1-J3 · Camera management API — 3 pts · Must · E03 · FR-CAM-01, FR-CAM-02
- [ ] CRUD `/cameras` with validation (RTSP URL format, unique code).
- [ ] `GET /cameras/status` merges Redis heartbeats (online / reconnecting / offline).
- [ ] `GET /internal/v1/cameras` matches the frozen fixture.

### P1-J4 · Frontend scaffold & app shell — 5 pts · Must · E04
- [ ] Vite React (JavaScript), Tailwind, shadcn/ui with `tsx: false`, tokens from `style_guide.md §B.3`, Barlow fonts.
- [ ] Router with protected routes; login page; `apiClient` with token refresh; TanStack Query provider.
- [ ] App shell: nav rail, page header, collapsible alert tray placeholder (layout §B.5).
- [ ] ESLint + Prettier + Vitest configured; one component test.

### P1-J5 · Live camera wall — 3 pts · Must · E04 · FR-LIVE-01
- [ ] Layouts 1/4/6 tiles; WebRTC (WHEP) playback from MediaMTX with HLS fallback via hls.js.
- [ ] VideoTile per §B.7 with status dot from `/cameras/status` (poll 5 s); double-click → single-tile focus.
- [ ] Settings → Cameras page (list/add/edit/disable) for admins.

### P1-J6 · CI pipeline — 3 pts · Must · E17 · NFR-MNT-03
- [ ] GitHub Actions: path-filtered jobs for Python (ruff, pytest) per service/lib, frontend (eslint, vitest, build), Docker build per service.
- [ ] PR template with story id + AC checklist; branch protection on `main`.

---

# Phase 2 — Perception, digital twin, indexing & playback (weeks 3–4)

**Goal / demo:** play back any camera with bounding boxes and track ids; density scrubber; twin rows and vectors visible in Postgres/Qdrant.

**Contracts frozen day 1:** `twin.v1`, `twinready.v1`, `.npz` layout, zones internal API.

## Divyansh — 23 pts

### P2-D1 · Perception worker & batched detection — 5 pts · Must · E05 · FR-PER-01, FR-PER-02
- [ ] Consumes `segment.v1`; decodes with PyAV; samples at `sample_fps` (default 2).
- [ ] Cross-camera batching (≤ 8 frames) into YOLO11s FP16; class filter per FR-PER-02.
- [ ] Adaptive sampling: 1 fps when consumer lag > 60 s, back to default when < 10 s.

### P2-D2 · Persistent multi-camera tracking — 5 pts · Must · E05 · FR-PER-03
- [ ] Per-camera ByteTrack instances; track ids formatted `cam03-t412`.
- [ ] Tracker state checkpointed to Redis per segment and restored on restart; ids continue across segment boundaries (test with a person crossing a boundary).
- [ ] Handles out-of-order segments by skipping state update and logging.

### P2-D3 · Attributes, motion & zones — 3 pts · Must · E05 · FR-PER-04
- [ ] Upper/lower dominant colour for persons, dominant colour for vehicles/bags (11 named colours).
- [ ] Speed (normalized units/s) and direction from centroid displacement.
- [ ] Zone membership via bottom-centre point-in-polygon; zones from internal API (fallback YAML), refreshed every 60 s.

### P2-D4 · Digital twin writer — 3 pts · Must · E05 · FR-PER-05
- [ ] Twin JSON conforms to `TwinV1`; track summaries (dwell, zones visited, best crop) computed.
- [ ] Written to `vms-twins`, crops to `vms-crops`; `twinready.v1` published.
- [ ] Contract test: produced twin validates against fixture schema.

### P2-D5 · SigLIP 2 embeddings — 5 pts · Must · E05 · FR-PER-06
- [ ] Keyframe embeddings every 2 s and one best-crop embedding per track per segment, FP16, L2-normalized.
- [ ] Stored as `.npz` (`frame_vectors`, `frame_ts`, `track_vectors`, `track_ids`) per contract.
- [ ] Sanity test: text "a red car" ranks a red-car crop above others in a small fixture set.

### P2-D6 · Perception benchmark on 4 GB — 2 pts · Must · E05 · NFR-PERF-01
- [ ] Script runs 2/4/6 simulated cameras for 20 min; records fps, p95 segment latency, VRAM peak, consumer lag.
- [ ] Results table committed to `ml/evaluation/results/` and default config chosen; `design_architecture.md §11.3` updated with measured VRAM.

## Jatin — 23 pts

### P2-J1 · Indexer service (Postgres) — 5 pts · Must · E06 · FR-IDX-01, FR-IDX-02
- [ ] Consumes `twinready.v1`; upserts `media.segments`, `vision.tracks`, `vision.track_segments`, `vision.minute_counts` (per camera/category/minute).
- [ ] Idempotent by `segment_id` (replaying a topic doesn't duplicate rows — test).
- [ ] Migrations for `media.*` and `vision.*`.

### P2-J2 · Qdrant collections & vector upserts — 3 pts · Must · E06 · FR-IDX-01
- [ ] Bootstrap script creates `frames`, `tracks` (and empty `knowledge`) with payload indexes per design §6.2.
- [ ] Indexer reads `.npz` and upserts points with deterministic ids (re-runs overwrite, no duplicates).
- [ ] Filtered search smoke test (`camera_id` + time range) returns expected fixture points.

### P2-J3 · Recordings API & HLS playlists — 5 pts · Must · E06 · FR-PLAY-01
- [ ] `GET /recordings/{camera}/segments?start&end` and `playlist.m3u8` generating a VOD playlist with presigned segment URLs and `#EXT-X-PROGRAM-DATE-TIME`.
- [ ] `GET /recordings/{camera}/density` from `vision.minute_counts`.
- [ ] `GET /twin/{camera}/frames?start&end` returns overlay-ready bboxes for a ≤ 60 s window.
- [ ] Gaps return explicit markers instead of silent skips.

### P2-J4 · Zones API — 2 pts · Must · E03 · FR-CAM-03
- [ ] CRUD zones with normalized polygon validation (3–32 points, within [0,1]), type and schedule JSON.
- [ ] `GET /internal/v1/zones` matches the frozen fixture.

### P2-J5 · Playback page — 5 pts · Must · E06 · FR-PLAY-01, FR-PLAY-02
- [ ] Camera + date/time range picker; hls.js playback of generated playlists.
- [ ] Timeline scrubber v1 (signature component, §B.6): density sparkline, playhead, drag to scrub, keyboard steps.
- [ ] Player time ↔ wall-clock mapping via program-date-time.

### P2-J6 · Detection overlay — 3 pts · Must · E06 · FR-PLAY-03
- [ ] Canvas overlay draws bboxes + track ids synchronized with the player (≤ 200 ms drift measured on a test clip).
- [ ] Toggle overlays; click a box → side panel with track summary (attributes, dwell, zones).

---

# Phase 3 — Events, correlation, alerts, GenAI gateway, annotation kickoff (weeks 5–6)

**Goal / demo:** walk into a restricted zone on camera → verified alert on dashboard in < 30 s → event on second camera linked into one group; zones and camera links configured in UI.

**Contracts frozen day 1:** `event.v1`, `correlation.v1`, `LLMGateway` interface + `models.yaml`, phase annotation export schema.

**Support track starts:** Kuldeep & Pankaj begin phase annotation (week 6).

## Divyansh — 23 pts

### P3-D1 · Events service & core rules — 5 pts · Must · E07 · FR-EVT-01
- [ ] Consumes `twinready.v1`, maintains per-camera sliding state (tracks, dwell, zone occupancy).
- [ ] Rules: `intrusion.restricted`, `intrusion.after_hours`, `loitering`, `crowding` with thresholds from `config/rules.yaml` overridable per camera/zone.
- [ ] Candidate debounce/extension logic; candidates persisted in `events.candidates` (migration included).
- [ ] Unit tests with synthetic twin sequences for every rule (positive + negative).

### P3-D2 · Advanced rules — 5 pts · Must · E07 · FR-EVT-01
- [ ] `abandoned_object` (static bag + owner distance/time logic) and `running`.
- [ ] Rules pluggable via a registry (`@rule("id")`), each with a JSON-schema for its params.
- [ ] Precision/recall quick check on 20 labelled ShanghaiTech/MEVA clips recorded in results.

### P3-D3 · LLM gateway & model registry — 5 pts · Must · E09 · FR-CFG-01…03
- [ ] `LLMGateway.chat` / `.vision` over LiteLLM for ollama, gemini, groq, openrouter; `response_model` validation + retry; fallbacks; timeouts.
- [ ] `config/models.yaml` with `local`, `hybrid`, `cloud` profiles; `VMS_LLM_PROFILE` switch.
- [ ] Redis GPU lease (acquire/heartbeat/release, Ollama unload on family switch) and Redis response cache.
- [ ] `FakeGateway` for tests; metrics `vms_llm_request_seconds`, `vms_llm_tokens_total`.
- [ ] Benchmark note: latency + VRAM for `qwen2.5vl:3b` and `qwen2.5:3b` on 4 GB; model tags verified.

### P3-D4 · VLM verification gate — 3 pts · Must · E07 · FR-EVT-02…05
- [ ] Builds ≤ 4 keyframes with drawn boxes; prompt `event_verify/1.0`; verdict JSON validated.
- [ ] Verified → `events.events` + `event.v1`; rejected stored with reason; `verify: false` rules bypass.
- [ ] Graceful degradation: gateway unavailable → event published as `verification.status=skipped` for low severity, held (retry queue) for high.

### P3-D5 · Phase annotation kit — 5 pts · Must · E10 · FR-RSN-02
- [ ] `ml/annotation/phase_guideline.md` with definitions and 3 worked examples per event type (taxonomy design §8.2).
- [ ] Label Studio temporal labelling config (video timeline with 5 phase labels + event type + primary view).
- [ ] Clip extraction script producing annotation tasks from UCF-Crime (8 classes) and MEVA multi-view incidents (≥ 250 candidate clips, all views per MEVA incident).
- [ ] Export converter → `phase_labels.jsonl` matching the frozen export schema; inter-annotator agreement script (temporal IoU between K & P on a 20-clip overlap set).


## Jatin — 23 pts

### P3-J1 · Camera links (topology) API — 2 pts · Must · E03 · FR-CAM-04
- [ ] CRUD topology edges (`overlap` with tolerance, `transit` with min/max, bidirectional flag) with validation.
- [ ] `GET /internal/v1/topology`.

### P3-J2 · Correlation service — 5 pts · Must · E08 · FR-COR-01…04
- [ ] Consumes `event.v1`; implements linking + union-find grouping + close rule (design §7.5) with `config/correlation.yaml` compatibility matrix.
- [ ] Persists `events.correlation_groups` / `correlation_links`; publishes `correlation.v1` (throttled updates + close).
- [ ] Unit tests: overlap link, transit link in window, out-of-window no link, incompatible types, group merge, single-event group close.

### P3-J3 · Alerts backend & notifier plugins — 5 pts · Must · E08 · FR-ALR-01…03
- [ ] API consumer for `event.v1`, `correlation.v1` creates/updates `core.alerts` per severity threshold.
- [ ] `WS /api/v1/ws` with JWT auth, role filtering, message types per design §9; Redis pub/sub fan-out (works with 2 API replicas).
- [ ] Ack/resolve endpoints with notes + audit log.
- [ ] `Notifier` interface with `DashboardNotifier` (on) and `EmailNotifier`, `TelegramNotifier` (implemented, disabled by default via `VMS_NOTIFY_CHANNELS`).

### P3-J4 · Alerts & events UI — 3 pts · Must · E08 · FR-ALR-01, FR-ALR-02
- [ ] Alert tray (AlertItem §B.7), live via WS, acknowledge/resolve with note dialog; `aria-live` per §B.10.
- [ ] Events page with filters; event detail with keyframes, VLM caption, clip playback, correlated events list.

### P3-J5 · Zone & camera-link editors — 3 pts · Must · E03 · FR-CAM-03, FR-CAM-04
- [ ] Polygon editor over a camera snapshot (add/move/delete points, name, type, schedule).
- [ ] Camera links editor (table + simple node diagram) for overlap/transit edges.

### P3-J6 · Caption & VQA annotation kit — 5 pts · Must · E10 · FR-RSN-03
- [ ] `config/vqa_bank.yaml`: 5–8 questions per event type.
- [ ] Label Studio template for per-phase, per-view caption + VQA verification.
- [ ] Kaggle notebook generating draft captions/VQA answers with the largest open VLM that fits (e.g. Qwen2.5-VL-7B) on phase-labelled clips; drafts imported as pre-annotations.
- [ ] Converter → `phavr_labels.jsonl`; script reports pseudo-label edit rate after human verification.

---

# Phase 4 — Multimodal search (weeks 7–8)

**Goal / demo:** implicit text query and image query return ranked clips with reasoning traces and masks; first retrieval benchmark numbers.

**Contracts frozen day 1:** `queryplan.v1`, `candidate.v1`, search response, grounding + image-search response.

**Support track:** K & P write ≥ 150 benchmark queries with ground truth (by end of week 8); annotation continues.

## Divyansh — 23 pts

### P4-D1 · Retrieval service & query decomposition — 5 pts · Must · E11 · FR-SRC-01, FR-SRC-02
- [ ] `services/retrieval` FastAPI app; `POST /search` accepts query, filters, `mode=fast|reason`.
- [ ] Prompt `query_decompose/1.0` → `QueryPlan` validated; relative times resolved with site timezone; filters from request override plan.
- [ ] 30 golden query → plan tests (with `FakeGateway` recordings) covering attributes, time, zones, implicit actions.

### P4-D2 · Coarse hybrid retrieval — 8 pts · Must · E11 · FR-SRC-03, FR-SRC-10
- [ ] SigLIP 2 text encoder on CPU; visual queries against `frames` and `tracks` with payload filters from the plan.
- [ ] Dense + sparse search on `knowledge` (event captions) for text queries.
- [ ] Reciprocal rank fusion; grouping hits into segment-window candidates (merge within 10 s per camera); top-K = 30.
- [ ] `mode=fast` returns in p95 ≤ 1 s on the Phase 2 archive (measured).
- [ ] Per-stage timings included in response for logging.

### P4-D3 · LLM reasoning rerank & traces — 5 pts · Must · E11 · FR-SRC-04
- [ ] Loads twin excerpts (only matched tracks ± context, token-capped) for candidates; batched prompts (5 candidates/call).
- [ ] Output per candidate: score 0–1, trace ≤ 60 words, `missing[]` sub-questions; validated with retry.
- [ ] Final ranking = weighted fused + reasoning score; weights configurable; emits `candidate.v1` to JIT for top-N with `missing`.

### P4-D4 · Search UI — 5 pts · Must · E11 · FR-SRC-01, FR-SRC-08
- [ ] Search page: query bar with example placeholder, camera/time filter chips, fast/reason toggle.
- [ ] Result cards: keyframe, camera, time, score, collapsible ReasoningTrace (§B.7), "Open in playback" at exact timestamp.
- [ ] Progressive rendering: fast results first, reasoned ranking replaces them when ready.
- [ ] Empty/error states per §B.8.

## Jatin — 23 pts

### P4-J1 · Image query path — 2 pts · Must · E11 · FR-SRC-06
- [ ] `POST /search/image` accepts upload or `{frame_uri, bbox}`; crops, embeds with SigLIP 2 vision (CPU), searches `tracks` with filters.
- [ ] Results grouped by track, sorted by score then time, same response shape as text search.

### P4-J2 · Object-level grounding — 5 pts · Must · E11 · FR-SRC-07
- [ ] `perception/grounding` module: `POST /internal/grounding {keyframe_uri, bbox}` → SAM 2.1-tiny mask → RLE cached in `vms-masks`.
- [ ] Shares the perception process/GPU; loads lazily; p95 ≤ 700 ms warm (measured).
- [ ] API `POST /search/grounding` proxies with caching by `(keyframe_uri, bbox)`.

### P4-J3 · JIT refinement — 5 pts · Must · E11 · FR-SRC-05
- [ ] Consumes `candidate.v1` with `missing[]`; asks `jit_vqa` on candidate keyframes; answers stored in `retrieval.jit_cache` keyed by `(segment_id, question_hash)`.
- [ ] Returns answers to the rerank stage; time budget per search (default 8 s), skipped gracefully when exceeded.
- [ ] Answers also indexed into `knowledge` (doc_type `jit_answer`) so later searches benefit.

### P4-J4 · Search API, logging & event-caption indexing — 3 pts · Must · E11 · FR-SRC-09
- [ ] API proxies `/search*` to retrieval with auth and timeouts.
- [ ] `retrieval.search_logs` stores query, plan, candidates, final results, per-stage latency, profile.
- [ ] Indexer consumes `event.v1` and writes captions into `knowledge` (dense + sparse) with payload.

### P4-J5 · Image search & mask UI — 3 pts · Must · E11 · FR-SRC-06, FR-SRC-07
- [ ] "Search by image" upload dialog and "Find similar" crop tool on any paused frame (playback, event detail).
- [ ] Mask overlay rendering on result keyframes, requested lazily when a card is visible.

### P4-J6 · Retrieval evaluation harness — 5 pts · Must · E18 · EV-01
- [ ] `ml/evaluation/retrieval`: `queries.jsonl` format + validation; ground-truth labelling guide for K & P.
- [ ] Metrics R@1/5/10, mAP, tIoU@0.3/0.5, latency per stage.
- [ ] Ablation runner: `embed`, `embed+filters`, `+rerank`, `+jit`, for `local` and `hybrid` profiles.
- [ ] Baseline report generated on the first 50 queries.

---

# Phase 5 — Phase-aware event reasoning (weeks 9–10)

**Goal / demo:** click *Analyze* on a correlated incident → phase timeline across views with per-phase captions/VQA; fine-tuned vs zero-shot numbers.

**Contracts frozen day 1:** `phasetimeline.v1`, `evidence.v1`, `incident.v1`, `incidentready.v1`.

**Dependency:** ≥ 150 phase-annotated clips by start of week 9 (minimum viable), target 250 by end of week 9.

## Divyansh — 22 pts

### P5-D1 · TG dataset builder — 3 pts · Must · E12
- [ ] `phase_labels.jsonl` → instruction JSONL: ≤ 16 timestamped frames (≤ 360 p) + prompt → phase JSON target.
- [ ] Multi-view samples include all views with camera tags; split 70/15/15 **by source video**; manifest + hash committed.
- [ ] Frames + JSONL packaged as a Kaggle dataset.

### P5-D2 · TG adapter fine-tuning — 8 pts · Must · E12
- [ ] Unsloth QLoRA notebook on Qwen2.5-VL-3B with hyperparameters from design §8.3; runs within one Kaggle session (checkpointing to resume).
- [ ] Experiment tracking (config, loss curves, val mIoU per epoch).
- [ ] Best adapter uploaded to `vms-models/tg/v1` with model card (data, metrics, limits).

### P5-D3 · TG evaluation — 3 pts · Must · E18 · EV-02
- [ ] `ml/evaluation/reasoning/phase`: mIoU and boundary MAE on test split.
- [ ] Baselines: zero-shot base 3B (same prompt) and zero-shot cloud VLM on ≤ 40 clips (free tier).
- [ ] Error analysis: confusion between adjacent phases, per event type, single vs multi-view.

### P5-D4 · Reasoning orchestrator — 5 pts · Must · E12 · FR-RSN-01, FR-RSN-04…06
- [ ] Consumes `correlation.v1` (closed, severity ≥ threshold) and `POST /events/{id}/analyze`; `reasoning.jobs` queue with `SKIP LOCKED`.
- [ ] Gathers synced clips for all cameras (window ±15 s), samples frames, runs TG → `phasetimeline.v1` → calls evidence module → stores bundle.
- [ ] Job progress via API WS `job.progress`; queue position exposed.
- [ ] Fallback chain: TG adapter → zero-shot base → cloud profile, recorded in provenance.

### P5-D5 · Adapter serving (`hf_local`) — 3 pts · Must · E12
- [ ] Gateway provider loads 4-bit base once and hot-swaps `tg` / `phavr` LoRA adapters via PEFT under the GPU lease.
- [ ] Pixel/frame caps configurable; OOM caught → retry with fewer frames.
- [ ] Measured VRAM and latency per call documented.

## Jatin — 22 pts

### P5-J1 · PhaVR dataset builder — 3 pts · Must · E12
- [ ] `phavr_labels.jsonl` → instruction JSONL for captioning and VQA tasks per phase × view (≤ 8 frames).
- [ ] Same video-level split as TG (shared manifest); packaged as a Kaggle dataset.

### P5-J2 · PhaVR adapter fine-tuning — 8 pts · Must · E12
- [ ] Unsloth QLoRA notebook (same base/hyperparameters), mixed caption + VQA batches.
- [ ] Experiment tracking; best adapter to `vms-models/phavr/v1` with model card.

### P5-J3 · PhaVR evaluation — 3 pts · Must · E18 · EV-02
- [ ] BLEU-4, METEOR, ROUGE-L, CIDEr for captions; exact/normalized-match accuracy for VQA, per view type.
- [ ] Baselines: zero-shot base 3B and cloud VLM subset; results table + qualitative examples.

### P5-J4 · Evidence builder — 5 pts · Must · E12 · FR-RSN-03, FR-RSN-04
- [ ] `reasoning/evidence`: for each phase × view, sample frames, run PhaVR caption + VQA bank for the event type.
- [ ] Assemble `evidence.v1` with stable evidence ids and frame URIs in `vms-evidence`; validated against contract.
- [ ] Skips empty phases/views; per-call timings in provenance.

### P5-J5 · Event reasoning view — 3 pts · Must · E12
- [ ] Event/correlation detail gains a "Reasoning" tab: timeline with phase band across camera lanes (§B.6), per-phase captions and Q&A, evidence frames.
- [ ] Clicking a phase plays all views for that phase in sync (≤ 4 views); job progress/queue shown while running.

---

# Phase 6 — Incident reports, assistant, daily reports, investigation (weeks 11–12)

**Goal / demo (feature complete):** incident report with causal chain + PDF; multi-turn assistant with citations; daily report PDF; investigation timeline with saved case.

**Contracts frozen day 1:** assistant tool endpoints (events/incidents/timeline query APIs), daily facts schema.

## Divyansh — 23 pts

### P6-D1 · Incident report synthesis — 8 pts · Must · E13 · FR-INC-01…03
- [ ] Hierarchical prompts: phase summaries → causal chain & contributing factors → final report, each schema-validated.
- [ ] Citation validator (every evidence id exists; each causal step and factor has ≥ 1); retry with error text ≤ 2; `failed` status with raw output.
- [ ] Persists `reasoning.incidents` (JSONB + S3 copy), publishes `incidentready.v1`, WS `incident.ready`.
- [ ] Golden tests on 5 fixture evidence bundles (schema-valid, citations valid).

### P6-D2 · RAG assistant agent & streaming — 8 pts · Must · E14 · FR-AST-02…04, FR-AST-06
- [ ] Tools per design §10.3 with JSON schemas; `count_objects` uses pre-defined parameterized SQL only.
- [ ] Agent loop (≤ 5 tool rounds), citation format enforcement, "nothing found" behaviour.
- [ ] `POST /assistant/sessions/{id}/messages` streams SSE events `token`, `tool_call`, `tool_result`, `citation`, `done`, `error`.
- [ ] 25 scripted conversations pass tool-selection and citation checks with `FakeGateway` recordings.

### P6-D3 · Conversation memory — 2 pts · Should · E14 · FR-AST-01, FR-AST-05
- [ ] Sessions/messages persisted; last 12 messages + rolling summary; tool results truncated to budget.

### P6-D4 · Assistant UI — 5 pts · Must · E14 · FR-AST-01, FR-AST-03
- [ ] Session list + chat column (§B.7); streaming render; tool activity lines; EvidenceChip citations opening clips/incidents.
- [ ] Suggested starter questions from the last 24 h; stop-generation button; error/retry states.

## Jatin — 23 pts

### P6-J1 · Daily security report job — 5 pts · Must · E15 · FR-RPT-01…04
- [ ] `DailyFacts` aggregation SQL; charts (events by hour/type/camera, alert response times).
- [ ] Narrative via gateway with numeric post-check (numbers must exist in facts) → regenerate once → template fallback.
- [ ] Jinja2 + WeasyPrint PDF per §B.11 → `vms-reports`; row in `reasoning.daily_reports`; indexed into `knowledge`.
- [ ] Entry point `python -m reasoning.reports.daily`; supercronic in Compose; `POST /reports/daily` on demand (≤ 7-day range).

### P6-J2 · Incident UI & PDF export — 5 pts · Must · E13 · FR-INC-04, FR-INC-06
- [ ] Incidents list (filters, severity, status) and report view per §B.7 with EvidenceChips and ProvenanceNote.
- [ ] Status/notes editing (operator+); incident PDF via the same PDF pipeline.

### P6-J3 · Incident indexing & similar incidents — 3 pts · Should · E13 · FR-INC-05
- [ ] Indexer consumes `incidentready.v1`, indexes report sections into `knowledge`.
- [ ] `GET /incidents/{id}/similar` returns ≤ 5 by hybrid similarity + same event type boost; shown in UI.
- [ ] Assistant tool endpoints for events/incidents/timeline exposed per frozen contract.

### P6-J4 · Investigation timeline & cases — 8 pts · Should · E16 · FR-INV-01…03
- [ ] Multi-camera timeline (lanes, events, correlation links, incidents) for a selected range.
- [ ] Synchronized playback of up to 4 cameras driven by one playhead (drift ≤ 300 ms).
- [ ] Shift-drag range → "Search in range" / "Save to case"; cases CRUD with bookmarked items and notes.

### P6-J5 · Daily reports UI — 2 pts · Must · E15 · FR-RPT-02, FR-RPT-04
- [ ] Reports list, "Generate report" dialog (date range), status while generating, preview + download PDF.

---

# Phase 7 — Kubernetes, cloud, observability, evaluation, hardening (weeks 13–14)

**Goal / final demo:** whole system on minikube (local) and a cloud VM (Compose); Grafana dashboards; full evaluation report.

**Contracts frozen day 1:** infra service names/ports in k8s (`deploy/k8s/base/infra/SERVICES.md`).

**Support track:** K & P run usability study and response-quality human ratings; final documentation.

## Divyansh — 23 pts

### P7-D1 · Kubernetes infra layer — 5 pts · Must · E17 · NFR-POR-01
- [ ] minikube setup script (docker driver, addons, `--gpus all` attempt).
- [ ] Strimzi Kafka (KRaft) + topics as `KafkaTopic` resources; CloudNativePG cluster; Qdrant Helm; Redis; object storage; MediaMTX (NodePort RTSP).
- [ ] Namespaces, PVCs, resource requests sized for a 16 GB laptop; `SERVICES.md` published.

### P7-D2 · GPU scheduling in Kubernetes — 5 pts · Must · E17
- [ ] NVIDIA device plugin; `vms.io/gpu-role` node labels; perception/reasoning request `nvidia.com/gpu`.
- [ ] Documented, tested fallback: GPU services on host Compose exposed to the cluster via `ExternalName`/Endpoints.

### P7-D3 · Observability — 5 pts · Should · E17 · NFR-OBS-01, NFR-OBS-02
- [ ] All metrics in design §15 exported; kube-prometheus-stack with ServiceMonitors (and Compose `obs` profile).
- [ ] Grafana dashboards: Pipeline health (lag, fps, segments), GenAI (latency/tokens per provider, queue depth), API (RPS, p95, errors).

### P7-D4 · Latency & throughput evaluation — 5 pts · Must · E18 · EV-04
- [ ] `ml/evaluation/latency` harness drives 2/4/6 cameras for 30 min per profile (local/hybrid/cloud).
- [ ] Measures NFR-PERF-01…05 p50/p95 from metrics + logs; results JSON + Markdown summary.

### P7-D5 · Resilience tests — 3 pts · Must · E17 · NFR-REL-01…04
- [ ] Chaos script restarts each worker mid-stream; verifies zero missing segments/events and no duplicates.
- [ ] DLQ replay tool; GPU/LLM-down scenario shows graceful degradation.

## Jatin — 23 pts

### P7-J1 · Kubernetes app layer — 5 pts · Must · E17 · NFR-POR-01
- [ ] Kustomize base + `minikube` overlay: Deployments/Services for all app services and frontend, ConfigMaps (models/rules/correlation), Secret generator, probes.
- [ ] ingress-nginx routes (`/`, `/api`), migrations `Job`, daily report `CronJob`, HPA on indexer.
- [ ] `make k8s-up` brings the full app up on minikube.

### P7-J2 · Cloud Docker deployment — 5 pts · Must · E17
- [ ] `docker-compose.prod.yml` with Caddy (TLS), `cloud` LLM profile, CPU perception (≤ 2 cameras) or pre-indexed archive mode.
- [ ] Deployed on a free/student-credit VM; runbook (provisioning, env, backups, update) in `deploy/compose/README.md`.

### P7-J3 · Continuous delivery — 3 pts · Must · E17
- [ ] GitHub Actions builds multi-arch images on tags/main and pushes to GHCR with semver + sha tags.
- [ ] Manual-dispatch deploy workflow to the VM over SSH.

### P7-J4 · Response-quality evaluation — 5 pts · Must · E18 · EV-03
- [ ] `ml/evaluation/response_quality`: judge prompts (faithfulness, relevance, citation precision) using a different model family; 20 % human-verification sheet.
- [ ] Incident report rubric (1–5 × accuracy, completeness, causality, actionability) forms + aggregation; schema-valid rate.
- [ ] Runs on ≥ 60 assistant questions and all test-set incidents; results summary.

### P7-J5 · Usability kit & security hardening — 5 pts · Must · E18, E17 · EV-05, NFR-SEC-*
- [ ] SUS questionnaire, 4 task scripts, consent note and results template for K & P.
- [ ] Hardening: rate limiting on auth/search/assistant, CORS allow-list, security headers (Caddy), presign expiry check, role × endpoint matrix passing, gitleaks clean.

---

# Support track — Kuldeep Nagar & Pankaj Raikar (not pointed)

| Weeks | Deliverable | Supports |
|---|---|---|
| 1–2 | Test plan skeleton mapped to SRS ids; Phase II slides update | All |
| 3–5 | Test cases for P1–P3 features; manual test runs each phase demo | QA |
| 6–9 | Phase annotation in Label Studio (≥ 150 by wk 9 start, 250 target) with 20-clip overlap for agreement | P5-D*, P5-J* |
| 7–9 | Verify caption/VQA pseudo-labels | P5-J* |
| 7–8 | ≥ 150 retrieval benchmark queries (≥ 50 % implicit) with ground-truth segments | P4-J6 |
| 11–12 | ≥ 60 assistant evaluation questions with expected evidence | P7-J4 |
| 13–14 | Usability study (≥ 8 participants), human ratings, final report & documentation | P7-J4, P7-J5 |

# Icebox (future work — not scheduled)

- Cross-camera person re-identification (appearance embeddings) for correlation.
- Depth-aware digital twin; pose/gaze modalities for reasoning.
- Email/Telegram notifications enabled in production.
- Audio event detection.
- Two-laptop k3s cluster with GPU node pool.
- Distilling adapters into a smaller edge model; Jetson deployment.
- Clip export with watermarking and chain-of-custody hashes.
