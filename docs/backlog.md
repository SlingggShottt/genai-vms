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
- [x] uv workspace with `libs/vms_common`, `libs/vms_db`, and empty service packages following `style_guide.md §A.1` layout.
- [x] Root `Makefile`: `make setup`, `make up PROFILE=…`, `make down`, `make test`, `make lint`.
- [x] Ruff + pytest config shared; pre-commit with ruff, nbstripout, gitleaks.
- [x] `CODEOWNERS` created from `design_architecture.md §3`.

### P1-D2 · Shared runtime library v1 — 5 pts · Must · E01 · NFR-REL-01, NFR-OBS-01
> **2026-10-08:** the integration test had never passed: its DLQ assertion looked headers up by `bytes` keys, but aiokafka returns `(str, bytes)` pairs, so the poison-message test raised `KeyError`. Fixed; both tests (consumed and committed; poison message to the DLQ with its origin topic and one attempt) pass, run against the dev broker with the same body because a second Kafka container did not fit in memory alongside the stack. The testcontainers fixture itself was not run.
- [x] `vms_common.config` (pydantic-settings), `logging` (structlog JSON with context binding), `ids` (uuid7), `metrics` helpers.
- [x] `vms_common.kafka`: async producer, consumer base class with validate → handle → commit, retry backoff, DLQ publish.
- [x] `vms_common.storage`: S3 client (put/get/stream/presign), URI parse/build helpers.
- [x] `contracts/segment.py` (`SegmentV1`) + fixture + round-trip test.
- [x] Integration test with testcontainers Kafka: message produced → consumed → committed; poison message → DLQ.
      **Written** (`libs/vms_common/tests/integration/test_kafka_consumer.py`), **not executed** — no Docker daemon in
      the environment this was built in. Run `make test-int` (needs Docker) before trusting it fully.

### P1-D3 · Infrastructure Compose — 3 pts · Must · E17
- [x] `deploy/compose/docker-compose.yml` with profile `infra`: Kafka (KRaft), kafka-ui, Postgres, Qdrant, Redis, object storage (buckets auto-created), MediaMTX.
- [x] Healthchecks on every container; `.env.example` documented.
      Two healthchecks (mediamtx, qdrant) are best-effort guesses at what's in the pulled image — unverified, see
      `deploy/compose/README.md` Troubleshooting.
      Update 2026-10-01 (first real run): the mediamtx guess was wrong — `bluenviron/mediamtx:latest` is a scratch
      image with no `wget`, so it was "unhealthy" forever and blocked `ingestion`/`camera-sim` (`depends_on:
      service_healthy`); switched to the `-ffmpeg` variant (same version), now healthy and gating works. The qdrant
      check passes but cannot see file-descriptor exhaustion (container "healthy" while HTTP was dead) — fixed with
      `ulimits.nofile`, not by a better probe.
- [x] Topic bootstrap script creates topics from `design_architecture.md §5.2`.
- [ ] `nvidia-smi` works inside a test GPU container on both laptops (documented in README troubleshooting).
      **Doc written** (`deploy/compose/README.md`); **not run on real hardware** — needs Divyansh and Jatin to each
      confirm on their own laptop and update the note with what worked.
      Update 2026-10-01 (Divyansh's laptop: RTX 3050 4 GB, driver 595.91, Ubuntu, Docker 29): host `nvidia-smi` works
      but Docker has no `nvidia` runtime (NVIDIA Container Toolkit not installed; `docker info` lists only `runc`),
      so the GPU container check is expected to fail and the Compose `perception` profile can't start there. Still
      open: install the toolkit and re-run. Verified fallback meanwhile: perception on the host with the repo's CUDA
      PyTorch (`uv run --package vms-perception python -m perception.main`; VRAM ~0.85 GiB after model load, up to
      ~1.4 GiB observed while processing; kept up with one 1080p camera in real time) with everything else in Compose.

### P1-D4 · Camera simulator — 3 pts · Must · E02 · FR-ING-06
- [x] `tools/camera_sim` reads a YAML (camera id → video file, start offset) and publishes looping RTSP streams to MediaMTX at real-time rate.
- [x] Synchronized start for multi-view datasets (WILDTRACK/MEVA offsets honoured).
- [x] Compose service in profile `tools`; doc for publishing a phone camera as a live source.
      Manifest parsing and ffmpeg command construction are unit-tested; not run end-to-end against real MediaMTX/video
      (no Docker daemon, no sample dataset — P1-D6 — in this environment).

### P1-D5 · Ingestion service — 8 pts · Must · E02 · FR-ING-01…05
- [x] One async worker per enabled camera, camera list from `GET /internal/v1/cameras` (fallback `config/cameras.yaml`), refreshed every 60 s.
      `GET /internal/v1/cameras` client is written but P1-J3 doesn't exist yet, so only the YAML fallback path is
      actually exercised so far — `libs/vms_common/contracts/camera.py` is a **proposed** day-1 contract per
      design_architecture.md §16, needs Jatin's review when P1-J3 lands.
- [x] FFmpeg segmenter writes 10 s MPEG-TS segments without re-encode; each uploaded to `vms-segments` with the key layout in design §6.3.
      Mechanics (segment muxer + list-file polling, keyframe extraction) verified locally against a synthetic ffmpeg
      source — see `adapters/segmenter.py` docstring for what that found (segments round up to the source's keyframe
      interval when it exceeds `segment_seconds`). Full pipeline (real RTSP → S3 → Kafka) not run end-to-end — no
      Docker daemon in this environment.
- [x] Keyframes at 1 fps uploaded to `vms-keyframes`.
- [x] `segment.v1` published per segment with correct UTC start/end; `gap_before=true` after reconnects.
- [x] Reconnect with exponential backoff ≤ 30 s; camera status heartbeat to Redis `camera:status:<id>` every 5 s.
- [x] Metrics `vms_ingest_segments_total`, `vms_stream_reconnects_total`.
- [ ] Runs 6 simulated cameras for 30 min with no missing segment ids (test script).
      **Script written** (`tests/smoke/check_no_missing_segments.py`); **not run** — needs the full stack (Docker,
      6 dataset videos from P1-D6) which isn't available in this environment. Run it once infra + camera_sim +
      ingestion are actually up.

### P1-D6 · Dataset acquisition scripts — 2 pts · Must · E10
- [x] `ml/datasets/download/` scripts + manifests for scoped subsets: WILDTRACK (full), MEVA (≤ 60 GB subset with ≥ 4 synchronized cameras), UCF-Crime (8 classes), ShanghaiTech Campus.
      Access URLs verified for real (fetched each dataset's page 27 Sep 2026 — see `ml/datasets/README.md`), but the
      scripts themselves were **not run** — no network budget in this environment for tens/hundreds of GB. MEVA's
      script lists/sizes/syncs a chosen prefix rather than hardcoding one, since exact bucket contents weren't
      verified live; ShanghaiTech falls back to a manual step (OneDrive isn't reliably scriptable).
- [x] `ml/datasets/README.md` lists licence/usage terms and disk sizes.

## Jatin — 24 pts

### P1-J1 · API service skeleton & database — 5 pts · Must · E01, E03
- [x] FastAPI app factory, router layout, error envelope (`style_guide.md §A.5`), request-id middleware, `/health`, `/ready`, `/metrics`.
- [x] `libs/vms_db`: async engine/session, base model, Alembic configured with per-domain schemas.
- [x] Migration 0001: `core.users`, `core.refresh_tokens`, `core.cameras`, `core.audit_log`.
- [x] Integration tests with testcontainers Postgres.

### P1-J2 · Authentication & RBAC — 5 pts · Must · E03 · FR-AUTH-01…05
- [x] Login returns access (15 min) + refresh (7 d) JWT; refresh rotation; logout revokes.
- [x] Argon2id hashing; seed admin from env on first start.
- [x] `require_role()` dependency; service-token dependency for `/internal/*`.
- [x] Users CRUD (admin only); audit log entries for login and user changes.
- [x] Role × endpoint test matrix generated from the router table.

### P1-J3 · Camera management API — 3 pts · Must · E03 · FR-CAM-01, FR-CAM-02
- [x] CRUD `/cameras` with validation (RTSP URL format, unique code).
- [x] `GET /cameras/status` merges Redis heartbeats (online / reconnecting / offline).
- [x] `GET /internal/v1/cameras` matches the frozen fixture.

### P1-J4 · Frontend scaffold & app shell — 5 pts · Must · E04
- [x] Vite React (JavaScript), Tailwind, shadcn/ui with `tsx: false`, tokens from `style_guide.md §B.3`, Barlow fonts.
- [x] Router with protected routes; login page; `apiClient` with token refresh; TanStack Query provider.
- [x] App shell: nav rail, page header, collapsible alert tray placeholder (layout §B.5).
- [x] ESLint + Prettier + Vitest configured; one component test.
      Verified for real: `npm install`, `npm run lint` (caught and fixed a `no-useless-catch` in `apiClient.js` and
      an a11y rule on the generic `Label` primitive), `npm run format:check`, `npm test` (2/2 passing), `npm run
      build`, and a dev-server smoke test (served real HTML, `main.jsx` transformed and returned 200). Also fixed a
      rules-of-hooks bug in `ProtectedRoute` (called `useCurrentUser` after a conditional early return) found on
      review, not by lint.

### P1-J5 · Live camera wall — 3 pts · Must · E04 · FR-LIVE-01
- [x] Layouts 1/4/6 tiles; WebRTC (WHEP) playback from MediaMTX with HLS fallback via hls.js.
      WHEP client (`lib/mediamtx.js`) hand-implemented against MediaMTX's documented offer/answer protocol — no
      client library exists for it. **Fallback path verified for real**: with no MediaMTX running, WHEP correctly
      fails, hls.js correctly fails, tile shows "No signal" with no crash (Playwright screenshot + zero console
      errors). **Not verified against an actual live stream** — this host has no `ffmpeg` and no spare disk budget
      today to pull another container and publish a test pattern (see PROGRESS.md session note re: disk). Verify
      against a real `make sim` camera before trusting the happy path.
- [x] VideoTile per §B.7 with status dot from `/cameras/status` (poll 5 s); double-click → single-tile focus.
      Verified for real end-to-end through the running API: layout switch (1/4/6), double-click focus with accent
      ring, live clock — all screenshotted and working.
- [x] Settings → Cameras page (list/add/edit/disable) for admins.
      Verified for real end-to-end: added a camera through the actual UI form (hit the real POST /cameras), it
      appeared in the list, disabled it through the UI (real PATCH), status flipped. Screenshotted at each step.

### P1-J6 · CI pipeline — 3 pts · Must · E17 · NFR-MNT-03
- [x] GitHub Actions: path-filtered jobs for Python (ruff, pytest) per service/lib, frontend (eslint, vitest, build), Docker build per service.
      Verified for real — not just written: pushed the workflow, watched it run on GitHub's own infrastructure (`gh
      run watch`), found and fixed a real bug (pytest exits 5 on zero tests collected, which several not-yet-built
      services hit — now treated as pass, not failure), re-ran, all 21 jobs green.
- [x] PR template with story id + AC checklist.
- [ ] Branch protection on `main`. Not applied. The `ci-success` job (aggregates every path-filtered job so branch
      protection doesn't need updating each time a service is added) is already in place as the thing to point a
      required status check at, once someone with admin on the repo (jatinbansal2994 has write, not admin) sets it
      up. Skipped for now by choice — revisit later.

---

# Phase 2 — Perception, digital twin, indexing & playback (weeks 3–4)

**Goal / demo:** play back any camera with bounding boxes and track ids; density scrubber; twin rows and vectors visible in Postgres/Qdrant.

**Contracts frozen day 1:** `twin.v1`, `twinready.v1`, `.npz` layout, zones internal API.

## Divyansh — 23 pts

### P2-D1 · Perception worker & batched detection — 5 pts · Must · E05 · FR-PER-01, FR-PER-02
- [x] Consumes `segment.v1`; decodes with PyAV; samples at `sample_fps` (default 2).
      Decoder verified against a real MPEG-TS file — caught and fixed a real bug (raw PTS doesn't start at 0 in
      MPEG-TS; see `adapters/decoder.py`).
- [x] Cross-camera batching (≤ 8 frames) into YOLO11s FP16; class filter per FR-PER-02.
      Batches within one segment's own frames rather than truly across concurrent cameras — a deliberate
      simplification, documented in `services/perception/README.md`. Real detection verified against
      ultralytics' own `bus.jpg` reference image (correctly found 1 bus + 4 people).
- [x] Adaptive sampling: 1 fps when consumer lag > 60 s, back to default when < 10 s.
      `AdaptiveSampler` implemented + unit tested with hysteresis; not yet wired to a real aiokafka lag metric
      (`_consumer_lag_seconds` is a stub — needs live infra, see worker.py TODO).

### P2-D2 · Persistent multi-camera tracking — 5 pts · Must · E05 · FR-PER-03
- [x] Per-camera ByteTrack instances; track ids formatted `cam03-t412`.
- [x] Tracker state checkpointed to Redis per segment and restored on restart; ids continue across segment boundaries (test with a person crossing a boundary).
      Verified for real against `supervision==0.30.5`: found and worked around an undocumented one-frame
      confirmation lag in `ByteTrack`'s output (a new object doesn't appear until the *next* frame), and verified
      restart + IoU re-association recovers the right track_num — see `adapters/tracker.py`'s docstring.
- [x] Handles out-of-order segments by skipping state update and logging.

### P2-D3 · Attributes, motion & zones — 3 pts · Must · E05 · FR-PER-04
- [x] Upper/lower dominant colour for persons, dominant colour for vehicles/bags (11 named colours).
      Verified for real on solid-colour crops and on real person crops from `bus.jpg`.
- [x] Speed (normalized units/s) and direction from centroid displacement.
- [x] Zone membership via bottom-centre point-in-polygon; zones from internal API (fallback YAML), refreshed every 60 s.
      `libs/vms_common/contracts/zones.py` is a **proposed** day-1 contract per design_architecture.md §16 (P2-J4
      doesn't exist yet, same treatment as camera.py) — needs Jatin's review when the real zones API lands.

### P2-D4 · Digital twin writer — 3 pts · Must · E05 · FR-PER-05
- [x] Twin JSON conforms to `TwinV1`; track summaries (dwell, zones visited, best crop) computed.
- [x] Written to `vms-twins`, crops to `vms-crops`; `twinready.v1` published.
- [x] Contract test: produced twin validates against fixture schema.
      Full write path (S3 + Kafka) not run end-to-end — no Docker daemon in this environment; the document-shaping
      logic (`twin_builder.py`) is real-data-tested via the tracker/detector verification above.

### P2-D5 · SigLIP 2 embeddings — 5 pts · Must · E05 · FR-PER-06
- [x] Keyframe embeddings every 2 s and one best-crop embedding per track per segment, FP16, L2-normalized.
      Verified for real: 768-d output (matches design_architecture.md §6.2), L2-normalized, ~35ms warm batch-of-8
      on an RTX 3050.
- [x] Stored as `.npz` (`frame_vectors`, `frame_ts`, `track_vectors`, `track_ids`) per contract.
- [x] Sanity test: text "a red car" ranks a red-car crop above others in a small fixture set.
      **Actually run, not just asserted**: `test_embedder_sanity.py` (marked `integration` — needs GPU + HF
      download) — clean diagonal, each colour's text query ranks its own crop highest by 4-6x margin over the
      others.

### P2-D6 · Perception benchmark on 4 GB — 2 pts · Must · E05 · NFR-PERF-01
- [ ] Script runs 2/4/6 simulated cameras for 20 min; records fps, p95 segment latency, VRAM peak, consumer lag.
      **Not run** — needs the live multi-camera stack (Docker), unavailable in this environment. What *was* done:
      real model-level GPU benchmarking (load + inference timing + peak VRAM, both models together) via
      `tests/smoke/gpu_pipeline_check.py` — see below.
- [x] Results table committed to `ml/evaluation/results/` and default config chosen; `design_architecture.md §11.3` updated with measured VRAM.
      `ml/evaluation/results/p2-d6-perception-benchmark.md` — real numbers (not estimates): ~966 MB peak VRAM for
      both models + batch-of-8 inference, well under the 4 GB budget. Explicitly scoped as model-level only, not
      the full multi-camera 20-min run the story asks for.

## Jatin — 23 pts

### P2-J1 · Indexer service (Postgres) — 5 pts · Must · E06 · FR-IDX-01, FR-IDX-02
- [x] Consumes `twinready.v1`; upserts `media.segments`, `vision.tracks`, `vision.track_segments`, `vision.minute_counts` (per camera/category/minute).
      `vision.tracks` is recomputed from its `track_segments` children on every write rather than merged
      incrementally — see `services/indexer/README.md` for why. The DB write path (`index_twin` against a real
      Postgres) is verified for real (see below); the Kafka consumer wiring itself (`worker.py`/`main.py`,
      `BaseConsumer` over `vms.twin.v1`) is not run against a live broker in this environment — verify with
      `make up PROFILE=infra,core,perception` + `make sim` before trusting the end-to-end path.
- [x] Idempotent by `segment_id` (replaying a topic doesn't duplicate rows — test).
      **Verified for real**: `make test-int` — `services/indexer/tests/integration/test_index_twin_idempotency.py`
      runs `index_twin` twice against a real testcontainers Postgres with the shared twin/twinready fixtures;
      row counts stay at 1 (segments, tracks, track_segments, minute_counts), and a second test checks the
      indexed rows' content matches the twin document. 3/3 passed.
- [x] Migrations for `media.*` and `vision.*`.
      Migration `0002_media_vision_initial` — **verified for real** via `make test-int`:
      `libs/vms_db/tests/integration/test_migrations_media_vision.py` applies the full Alembic history to a
      throwaway Postgres container and round-trips a row through every new table's FKs. 2/2 passed (this and
      the existing 0001 test).

### P2-J2 · Qdrant collections & vector upserts — 3 pts · Must · E06 · FR-IDX-01
- [x] Bootstrap script creates `frames`, `tracks` (and empty `knowledge`) with payload indexes per design §6.2.
      `deploy/compose/scripts/create_qdrant_collections.py` (`make qdrant-collections`), backed by
      `vms_common.qdrant.collections.ensure_collections` (shared with the indexer's own startup call, and with
      retrieval later — design §6.2 notes "query side: D"). **Verified for real** via `make test-int`.
- [x] Indexer reads `.npz` and upserts points with deterministic ids (re-runs overwrite, no duplicates).
      One point per `twin.frames[i]` / `twin.tracks[i]` — `tracks` collection is per (track_id, segment_id), not
      one point merged across a track's whole life; see `services/indexer/README.md` for why. **Verified for
      real**: `test_replaying_index_embeddings_does_not_duplicate_points` upserts the fixture twin's embeddings
      twice against a real Qdrant and asserts the point counts stay at 1 each.
- [x] Filtered search smoke test (`camera_id` + time range) returns expected fixture points.
      **Verified for real**: `test_filtered_search_by_camera_and_time_range_returns_the_expected_point` — a
      `camera_id` + `ts` range filter on `frames` returns exactly the fixture's point; a mismatched `camera_id`
      returns none, proving the filter is load-bearing, not a no-op.
      Test container pinned to `qdrant/qdrant:v1.11.5` to match the real compose pin, and `qdrant-client` pinned
      to `<1.12` to match it (a newer client against that server warned on a >1-minor-version gap — see
      `libs/vms_common/pyproject.toml`).

### P2-J3 · Recordings API & HLS playlists — 5 pts · Must · E06 · FR-PLAY-01
- [x] `GET /recordings/{camera}/segments?start&end` and `playlist.m3u8` generating a VOD playlist with presigned segment URLs and `#EXT-X-PROGRAM-DATE-TIME`.
      **Verified for real** via `make test-int`: `services/api/tests/integration/test_recordings.py` against a real
      Postgres + S3-compatible store (see note below on which one). No transcoding — a presigned url always serves
      its segment's whole `.ts` file, per design's "no transcoding" constraint; a request window that starts/ends
      mid-segment gets a little extra footage at the edges rather than a trimmed file.
- [x] `GET /recordings/{camera}/density` from `vision.minute_counts`.
      Sums across categories, re-buckets to the requested `bucket` seconds, zero-fills empty buckets (a sparkline
      needs a continuous series — documented as a deliberate departure from `vision.minute_counts`'
      absence-means-nothing convention). Verified for real.
- [x] `GET /twin/{camera}/frames?start&end` returns overlay-ready bboxes for a ≤ 60 s window.
      Fetches each covering segment's twin JSON live from S3 (Postgres only has track summaries, not per-frame
      boxes); rejects a window > 60s with 400. Verified for real.
- [x] Gaps return explicit markers instead of silent skips.
      One shared `build_timeline` (pure, unit-tested) drives both the JSON `segments` response (`type: "gap"` items)
      and the playlist (`#EXT-X-DISCONTINUITY` for an *interior* gap only — a leading/trailing gap has nothing to
      be discontinuous from, so gets no marker). Found and fixed a real bug here during testing: the first playlist
      implementation marked a trailing gap too; fixed with a deferred-marker approach (only emit
      `#EXT-X-DISCONTINUITY` once a segment is actually known to follow), now unit-tested for exactly that case.
      Follow-up (first end-to-end demo run, 2026-10-01): marking only gaps was not enough. Ingestion's segmenter
      writes each `.ts` with `-reset_timestamps 1`, so *every* segment boundary is a timestamp discontinuity;
      without a marker hls.js placed a segment fetched after a seek past the buffered range at the wrong time and
      the player ended early (duration collapsed to the buffered length). The playlist now emits
      `#EXT-X-DISCONTINUITY` before every segment after the first (a gap plus a boundary still yields one marker).

      Role × endpoint matrix (`test_role_matrix.py`) extended to cover all four new endpoints (all roles read).

      **S3-compatible store note**: the integration tests use `adobe/s3mock`, not real MinIO — both
      `minio/minio` (Docker Hub) and `quay.io/minio/minio` (what this compose file's `minio` service was
      pinned to) returned 401/404 on every tag when pulled in this environment; MinIO tightened anonymous-pull
      access since that pin was written. **Fixed** (2026-09-30, separately from this story):
      `deploy/compose/docker-compose.yml`'s `minio` service now pins `bitnamilegacy/minio` instead — verified
      for real (healthcheck, bucket auto-creation via `MINIO_DEFAULT_BUCKETS`, and a real boto3 `S3Client`
      put/get/presigned-GET round-trip, all through actual `docker compose up`); `minio-init` and
      `create_buckets.sh` are gone, no longer needed. `docs/techstack.md §7` and
      `deploy/compose/README.md` updated. The test fixture here still uses `s3mock` rather than real MinIO —
      lighter weight for a unit-ish integration test, no strong reason to switch now that MinIO itself works.

### P2-J4 · Zones API — 2 pts · Must · E03 · FR-CAM-03
- [x] CRUD zones with normalized polygon validation (3–32 points, within [0,1]), type and schedule JSON.
      `GET/POST /cameras/{id}/zones`, `PATCH/DELETE /zones/{id}` (read: all, write: admin) — matches
      design_architecture.md §9 exactly, including the mixed nested/flat path shape. `core.zones` (migration 0003)
      FKs `camera_id` to `core.cameras.id` with `ondelete=CASCADE`. Polygon validation
      (`api/domain/zones.py::validate_polygon`, pure, unit-tested) mirrors `ZoneInternal`'s own check. Verified for
      real via `make test-int`: full CRUD lifecycle, invalid-polygon rejection, unknown-camera 404,
      null-for-non-nullable-field rejection, `schedule` clear-to-null.
- [x] `GET /internal/v1/zones` matches the frozen fixture.
      `camera_id` in the internal contract is the camera's **code**, not its UUID `core.cameras.id` — different
      from the public zones API's own `camera_id`, matching the same split `camera.py`'s `CameraInternal`
      already has (code for internal/Kafka-facing consumers, UUID id for the public REST API). Finalized
      `libs/vms_common/contracts/zones.py`'s "proposed, review when P2-J4 lands" docstring now that it's landed —
      field shapes matched the fixture as-is, no changes needed. Verified for real, including that a user JWT
      (not a service token) is rejected.

      Role × endpoint matrix extended to cover all four new endpoints (76 test cases total now).

      **Follow-up (2026-09-30, not part of this story's AC but prompted by reviewing it)**: the camera
      code-vs-UUID split this story made explicit for zones already existed for cameras/segments/tracks and was
      only ever documented in scattered docstrings. Hardened it: `libs/vms_common/types.py` adds `CameraCode`/
      `CameraId` (`NewType` over `str` — zero runtime effect, confirmed with Pydantic v2 and by re-running
      perception's and ingestion's own unit tests unchanged) and design_architecture.md §5.1 now states the rule
      once, explicitly. Applied to every contract/model/schema field where the distinction actually matters
      (`CameraInternal`, `ZoneInternal`, `SegmentV1`, `TwinV1`, `TwinReadyV1`, `core.cameras.code`,
      `media.segments.camera_id`, `vision.*.camera_id`, and the relevant `services/api/src/api/schemas.py`
      fields) — not touching Divyansh's perception/ingestion source files themselves, since the contract-layer
      typing is what's load-bearing and NewType requires no call-site changes to be safe.

### P2-J5 · Playback page — 5 pts · Must · E06 · FR-PLAY-01, FR-PLAY-02
- [x] Camera + date/time range picker; hls.js playback of generated playlists.
      `frontend/src/features/playback/pages/PlaybackPage.jsx`. hls.js loads the `.m3u8` manifest directly (not
      through `lib/apiClient.js`), so the bearer token is attached via hls.js's own `xhrSetup` hook
      (`features/playback/api.js::hlsAuthConfig`) — presigned segment URIs inside the playlist need no auth of
      their own.
- [x] Timeline scrubber v1 (signature component, §B.6): density sparkline, playhead, drag to scrub, keyboard steps.
      Reduced to one lane — no event markers/phase band/correlation links, those need data from phase 3+ stories
      that don't exist yet. `components/TimelineScrubber.jsx`: click/drag to scrub, ← → step 1s, Shift+← →
      step 10s, per §B.6's interaction spec.
- [x] Player time ↔ wall-clock mapping via program-date-time.
      `features/playback/lib/programDateTime.js` — pure, unit-tested (11 tests): reads hls.js's own parsed
      `fragment.programDateTime`, clamps correctly past either end of the loaded range, and (a case easy to miss)
      snaps forward to the next fragment when scrubbed into a genuine wall-clock gap between two segments, as
      opposed to the player-time axis, which stays contiguous across a `#EXT-X-DISCONTINUITY`.

      **Verified for real**: applied migrations 0002/0003 to the team's real dev Postgres (additive only, didn't
      touch existing data), started a second `services/api` instance on a spare port with current code (left the
      team's existing one untouched), and drove the actual page through a real login with Playwright — camera
      picker populated from real camera rows, timeline scrubber rendered and responded to both click-to-scrub and
      the keyboard step (confirmed exactly 1000ms per press), no unexpected console errors. **Not verified**:
      actual HLS video frames playing — no real ingestion pipeline has produced recorded segments in this
      environment, so the page correctly shows its "Playback failed" fallback instead of crashing; verify the
      full happy path once real footage exists (`make sim` + ingestion/perception/indexer running for a while).

### P2-J6 · Detection overlay — 3 pts · Must · E06 · FR-PLAY-03
- [x] Canvas overlay draws bboxes + track ids synchronized with the player (≤ 200 ms drift measured on a test clip).
  Drawn on a `requestAnimationFrame` loop reading `videoEl.currentTime` directly each frame (not React state,
  which only updates on `timeupdate`) and mapped to wall-clock via the same `programDateTime.js` helper the
  scrubber uses, against the nearest `/twin/{camera}/frames` sample within a 1s staleness budget.
- [x] Toggle overlays; click a box → side panel with track summary (attributes, dwell, zones).
  `GET /tracks/{track_id}` (new, `services/api/src/api/api/tracks.py`) backs `TrackSummaryPanel.jsx`; dwell is
  summed from `vision.track_segments` since a track can leave and re-enter frame within its overall span.
  Verified: 80/80 role-matrix integration tests pass (including 4 new ones seeding a real `vision.tracks` row
  via `db_session_factory`, since tracks are only ever written by the indexer, not creatable through the API);
  ruff clean; frontend lint/Vitest/`npm run build` all pass. Not verified against real footage — no indexed
  twin data exists in this dev environment yet (same caveat as P2-J5).

---

# Phase 3 — Events, correlation, alerts, GenAI gateway, annotation kickoff (weeks 5–6)

**Goal / demo:** walk into a restricted zone on camera → verified alert on dashboard in < 30 s → event on second camera linked into one group; zones and camera links configured in UI.

**Contracts frozen day 1:** `event.v1`, `correlation.v1`, `LLMGateway` interface + `models.yaml`, phase annotation export schema.

**Support track starts:** Kuldeep & Pankaj begin phase annotation (week 6).

## Divyansh — 23 pts

### P3-D1 · Events service & core rules — 5 pts · Must · E07 · FR-EVT-01
- [x] Consumes `twinready.v1`, maintains per-camera sliding state (tracks, dwell, zone occupancy).
      `EventsConsumer` fetches the twin and runs the pure engine (`domain/engine.py`); the sliding state is a set of
      per-(rule, zone, track) *episodes* (first/last seen, frames, tracks) — i.e. dwell and zone-occupancy runs —
      checkpointed to Redis after the candidates are written, so a restart resumes a half-finished stay and a
      redelivered twin is skipped. Verified on the real stack: container restart left all 175 candidates and the
      open ones intact, 0 duplicate/split episodes, lag 0.
- [x] Rules: `intrusion.restricted`, `intrusion.after_hours`, `loitering`, `crowding` with thresholds from `config/rules.yaml` overridable per camera/zone.
      `@rule("<id>")` registry with a typed params model per rule; `config/rules.yaml` is validated at startup
      (unknown rule/param, bad value or unscoped override stops the service). Overrides resolve rule < camera < zone <
      camera+zone. Run for real on cam01 with demo zones: restricted-yard → `intrusion.restricted`, a scheduled zone →
      `intrusion.after_hours`, plaza → `crowding` (peak 15 vs limit 8, 99 distinct tracks, 80 s, 8 segments) and,
      with a scratch `dwell_s: 8` override, `loitering` incl. stays spanning two segments. **Not verified:** loitering
      at its 60 s default (nobody lingers that long in the demo footage), more than one camera live, zones from the
      API (the YAML fallback was used — the API isn't a Compose service yet). Semantics the design left open (decided
      here, documented in `design_architecture.md §7.3` and the service README): a zone's schedule is its normal hours;
      `intrusion.after_hours` also takes `min_frames` (default 2); thresholds are inclusive; unlisted rules stay on.
- [x] Candidate debounce/extension logic; candidates persisted in `events.candidates` (migration included).
      Migration `0004` (generated, then hand-fixed: the autogenerate draft would have dropped `alembic_version`).
      Deterministic UUIDv5 ids (`camera|rule|zone|track|start_ts`) + a monotonic upsert (end/score only grow, ids
      unioned, `closed` final) make replays no-ops: two independent live runs over the same twins produced the same 324
      ids; integration tests (real Postgres) cover redelivery, crash between write and checkpoint, state loss, restart.
- [x] Unit tests with synthetic twin sequences for every rule (positive + negative).
      128 unit tests (`services/events/tests/unit`) over multi-segment synthetic sequences; a 15-variant mutation check
      (break the engine/rules/config/id on purpose) found one hole — a gap longer than the debounce *inside* one
      segment — which now has its own test. Plus 18 consumer/repository integration tests (Postgres via
      testcontainers) and 5 + 1 for the model/migration in `libs/vms_db`.
      Open: the VLM gate (P3-D4) and `events.events` / `event.v1` publication are not part of this story.

### P3-D2 · Advanced rules — 5 pts · Must · E07 · FR-EVT-01
- [x] `abandoned_object` (static bag + owner distance/time logic) and `running`.
      Both are camera-wide rules (new `CameraRule` kind: no zones needed, NULL zone on the candidate, a
      JSON `memory` scratchpad saved with the camera state so a restart mid-wait loses nothing; `Hit.since`
      lets `abandoned_object` date its candidate from when the owner walked away). Defaults per design §7.3
      (T 30 s, r 0.08, T2 20 s; S 0.35/s, k 3); `static_epsilon` defaults to 0.03 (the design names ε but gives no
      value). 74 new unit tests (35 `abandoned_object`, 15 `running`, 23 schema, 1 registry), 4 integration
      tests through the real consumer + Postgres; a 32-variant mutation check over the whole engine found two
      holes in the new code (a bag lost across a gap with no frames at all; frames with nothing detected), both now
      tested. Verified on the real stack: the live container (design defaults) raised **no** `running` or
      `abandoned_object` candidate from the busy-street demo footage (fastest walker 0.175/s vs the 0.35 limit;
      nothing static and unattended) — the right answer; with deliberately relaxed thresholds in an isolated scratch
      run they fired (175 abandoned, 341 running, all NULL-zone), which is plumbing evidence, not accuracy evidence.
      The state saved by the P3-D1 build (no `memory` field) loaded into the new build without complaint.
- [x] Rules pluggable via a registry (`@rule("id")`), each with a JSON-schema for its params.
      The registry came with P3-D1; each `Params` model now yields a JSON Schema (`rule_param_schemas()`), and
      `config/rules.schema.json` — generated from the registry by `python -m events.schema_export`, kept honest by
      a drift test, validated with the real `jsonschema` library against the shipped `rules.yaml` and against the 12
      mistakes the loader rejects — lets editors validate/autocomplete `rules.yaml` (added `jsonschema` as a dev dep).
- [ ] Precision/recall quick check on 20 labelled ShanghaiTech/MEVA clips recorded in results.
      **Not done.** Neither dataset is on this machine (`ml/datasets/` holds only the download scripts) and there are
      no labelled clips, so any number reported here would be invented. It needs: the clips downloaded
      (`ml/datasets/download/`), a ground-truth label per clip for running / abandoned object, perception run over
      them to produce twins, then a harness in `ml/evaluation/` that replays the twins through
      `events.domain.engine.process_twin` with the rule configuration under test and scores candidates against the
      labels. The engine is pure and deterministic, so the replay half is straightforward once the data exists.

### P3-D3 · LLM gateway & model registry — 5 pts · Must · E09 · FR-CFG-01…03
- [x] `LLMGateway.chat` / `.vision` over LiteLLM for ollama, gemini, groq, openrouter; `response_model` validation + retry; fallbacks; timeouts.
      `libs/vms_common/llm/` (design §11.1 documents the behaviour as built): per model of a task in order — cache →
      GPU lease → provider call → validate (a malformed reply is shown its errors and re-asked, `validation_retries`
      default 2; fenced / prose-wrapped / `<think>` JSON needs no retry) → cache. Any provider failure moves to the
      next model; the exception type follows the primary (`LLMUnavailableError` → 503, `LLMOutputError` → 422,
      `LLMRequestError` = caller bug). Streaming and tool calls included; `vision()` enforces `max_images` and shrinks
      to `max_image_edge`. **Verified live only for ollama**: the real gateway → LiteLLM → Ollama → `qwen2.5:3b` and
      `qwen2.5vl:3b` on the RTX 3050 (structured plan, vision verdict on an image, repeat served from the cache,
      lease unloading the displaced model). Gemini / Groq / OpenRouter run through the same LiteLLM path but were
      **not called live** (no keys here) — only their missing-key and error-mapping paths are tested.
      Two things only the real run showed: litellm makes a *blocking* `/api/show` call to Ollama while pricing a call
      (and `register_model()` does too, at the wrong host) — avoided by declaring the models in its price map; and
      Ollama refuses 4-image requests at its default 4096-token context, so `num_ctx` is now a registry setting.
- [x] `config/models.yaml` with `local`, `hybrid`, `cloud` profiles; `VMS_LLM_PROFILE` switch.
      The design's registry plus a `tasks:` block for provider-independent behaviour; all three profiles are validated
      at load for completeness (a profile missing a task, an unknown key, a bad fallback, an `extends` cycle all stop
      startup). Switching `VMS_LLM_PROFILE` re-resolves every task with no code change (tested for rerank and
      event_verify across the three profiles). Groq entries use `openai/gpt-oss-120b`: LiteLLM's catalogue lists the
      design's `llama-3.3-70b-versatile` as deprecated since 2026-08-16.
- [x] Redis GPU lease (acquire/heartbeat/release, Ollama unload on family switch) and Redis response cache.
      Lease = Lua on Redis's clock: same family shares, a different family waits, a queued family goes first, a waiter
      that gives up withdraws its place, a crashed holder lapses after its TTL, Redis down ⇒ no unleased local run (the
      fallback answers instead). Cache key = task + model + messages (incl. image data) + schema + params; only
      validated results; an outage is a miss. 24 lease + 9 cache unit tests on fakeredis and 10 on a real Redis container
      (`make test-int`); the lease caught one design bug in testing (a waiter that timed out left a ghost queue
      marker that refused new calls for 2 s).
- [x] `FakeGateway` for tests; metrics `vms_llm_request_seconds`, `vms_llm_tokens_total`.
      `vms_common.llm.testing.FakeGateway` (scripted queues, bare values, exceptions, callables, JSON recordings with
      recorded failures; same JSON extraction/validation as production; running out of answers fails loudly) and
      `ScriptedBackend` for the gateway's own tests. Metrics as designed plus retries, fallbacks, cache and lease-wait
      series (design §15). 320 unit tests; a 66-variant mutation check (break the gateway/lease/registry/cache/parser/
      adapter on purpose) kills all 66. Its first pass had 7 survivors: five were real test gaps (now covered), one was
      a redundant cache-key input (removed), one an equivalent mutant (dropped).
- [x] Benchmark note: latency + VRAM for `qwen2.5vl:3b` and `qwen2.5:3b` on 4 GB; model tags verified.
      **Benchmark done, tag verification half done.** `ml/evaluation/results/p3-d3-llm-benchmark.md` (harness:
      `ml/evaluation/llm_benchmark.py`): the text model is 100 % on the GPU (2.4 GB, 0.25 s warm); the vision model
      is only ~53 % on the GPU (rest on CPU; 18–31 % beside perception) — 1 / 2 / 4 images ≈ 3 / 5 / 11 s warm,
      8–14 s cold — and each image costs ≈ 1,050 tokens at any pixel size. Both Ollama tags verified (exist, pulled, run).
      **Open:** the Gemini and Groq ids were checked only against LiteLLM's catalogue, never against the live APIs.
      With keys in `.env`, `VMS_LLM_PROFILE=cloud` plus one call per `models.yaml` entry closes this; fix any tag
      that answers "model not found" in `config/models.yaml`.

### P3-D4 · VLM verification gate — 3 pts · Must · E07 · FR-EVT-02…05
- [x] Builds ≤ 4 keyframes with drawn boxes; prompt `event_verify/1.0`; verdict JSON validated.
- [x] Verified → `events.events` + `event.v1`; rejected stored with reason; `verify: false` rules bypass.
- [x] Graceful degradation: gateway unavailable → event published as `verification.status=skipped` for low severity, held (retry queue) for high.

> Run on live footage 2026-10-04 (Qwen2.5-VL-3B via Ollama): 12 candidates decided, 6 verified and 6 rejected with reasons. Precision/recall with and without the gate still needs labelled clips (design §13).

### P3-D5 · Phase annotation kit — 5 pts · Must · E10 · FR-RSN-02
- [x] `ml/annotation/phase_guideline.md` with definitions and 3 worked examples per event type (taxonomy design §8.2).
  - A draft: the taxonomy still needs the project guide's approval (design §8.2). The examples are illustrative scenarios, not from the datasets.
- [x] Label Studio temporal labelling config (video timeline with 5 phase labels + event type + primary view).
  - One config per number of views (1-4); all four validate with Label Studio's own `LabelInterface`, which also caught that a label `alias` would replace the stored phase name. Not driven in a running Label Studio, and the shape of a real timeline export (frame numbering) is assumed from its documentation.
- [x] Clip extraction script producing annotation tasks from UCF-Crime (8 classes) and MEVA multi-view incidents (≥ 250 candidate clips, all views per MEVA incident).
  - MEVA, run on the real annotation repo: 361 candidates from 179 slots (2,131 before capping near-duplicates), every one with 2-3 synchronised views; cuts verified frame-aligned with real ffmpeg. **MEVA is everyday activity, not incidents**: abandoned packages appear in 1 clip and thefts in 4, none multi-view, so its candidates are activity episodes (drop-offs, pick-ups, hand-overs), whether to count them is the guide's call. UCF-Crime is **not verified against the real files** (host unreachable): the reader follows the published annotation convention and was run on fixtures only.
- [x] Export converter → `phase_labels.jsonl` matching the frozen export schema; inter-annotator agreement script (temporal IoU between K & P on a 20-clip overlap set).
  - Schema frozen as `phase_labels.v1`. No agreement figures exist yet: they need K and P's annotations.


## Jatin — 23 pts

### P3-J1 · Camera links (topology) API — 2 pts · Must · E03 · FR-CAM-04
- [x] CRUD topology edges (`overlap` with tolerance, `transit` with min/max, bidirectional flag) with validation.
      `GET/POST /topology/edges` (`?camera_id=` for edges touching a camera), `PATCH/DELETE /topology/edges/{id}`;
      read: any role, write: admin (in the role matrix). Overlap takes `tolerance_s` (default 5 s, always two-way),
      transit takes `min_s..max_s` (one-way unless `bidirectional`); anything that does not fit the type, a self-link,
      a missing camera (404) or cameras on different sites are rejected with the reason. Duplicates are 409, including
      the reverse of an overlap edge and a transit edge a bidirectional one already covers. `core.topology_edges`
      (migration `0005`) enforces the same rules itself with CHECK constraints, a unique pair and a partial unique
      index on the unordered overlap pair, so concurrent creates give one 201 and 409s, never a 500 (tested with 8
      parallel requests). PATCH changes parameters only. 61 unit tests (rules, schemas, contract, model), 24 API
      integration tests and 2 migration tests (real Postgres, incl. downgrade-then-upgrade); a 41-variant mutation
      check kills 40, the survivor being an equivalent mutant (applying a `null` to a field validation already
      guarantees is null). Found on the way: migration `0003` (zones) leaves `core.zone_type` behind on downgrade,
      so downgrade-then-upgrade fails — not changed here (merged migrations are never edited); `0005` drops its type.
- [x] `GET /internal/v1/topology`.
      Service-token gated; reports camera **codes** (what correlation sees in `event.v1`), shape =
      `vms_common.contracts.topology.TopologyInternalResponse` + `fixtures/topology_internal.json` (round-trip tested; the
      integration test validates the live response against the contract). Not done here: the editor UI (P3-J5).

### P3-J2 · Correlation service — 5 pts · Must · E08 · FR-COR-01…04
- [x] Consumes `event.v1`; implements linking + union-find grouping + close rule (design §7.5) with `config/correlation.yaml` compatibility matrix.
      `services/correlation` (README has the algorithm as built; design §7.5 "As built"). A new event is scored against
      the events of the site's open groups — camera-graph edge window, then `0.7·fit + 0.3·compat ≥ 0.5` — and joins or
      merges the groups it links (the oldest survives); `max_group_events` caps runaway chains; a group closes when its
      last event ended more than *longest transit window of its cameras + 30 s* ago. `config/correlation.yaml` is
      validated at startup (a typo stops the service). The camera graph comes from `GET /internal/v1/topology` with a
      `config/topology.yaml` fallback (the api is not a Compose service yet, so the fallback is what runs).
      Contracts defined here because nothing else had: `event.v1` (provided by D, P3-D4, built against fixtures) and
      `correlation.v1` (adds `merged` status + `merged_into`, `revision`, `event_types` to the design's sketch).
- [x] Persists `events.correlation_groups` / `correlation_links`; publishes `correlation.v1` (throttled updates + close).
      Migration `0006`; revision-guarded upserts; an event already in any group is ignored on redelivery; a change stays
      `publish_pending` until Kafka acknowledges it, so a crash or outage costs a duplicate, never a lost message. Open
      groups are announced at creation then at most every 5 s; closed/merged at once. One instance per consumer group
      (a lock serialises the consumer and the sweeper).
- [x] Unit tests: overlap link, transit link in window, out-of-window no link, incompatible types, group merge, single-event group close.
      101 unit tests (scoring incl. both fit curves and every edge direction, engine, config, topology, adapters) plus
      38 integration tests on real Postgres/Kafka: repository, consumer and sweeper flows (all six arrival orders of the
      fixture scenario, redelivery, restart, Kafka outage, a crashed publish, a hung Kafka not stalling event handling,
      20 concurrent deliveries beside sweeps) and
      one end to end over a Kafka container (a poison message is dead-lettered and does not stop the consumer). The
      fixture scenario is replayed and must reproduce `correlation_v1.json`. A 55-variant mutation check kills 54; the
      survivor is an equivalent mutant (the same-camera guard, which a validated graph can never reach).
      **Verified live:** the real service against the dev Kafka with a scratch database/topics — three events became two
      groups, the third bridged them (links 23 s / 0.5365 and 53 s / 0.6973, exactly the fixtures'), five messages came
      out keyed by site; killed and restarted it (lag 0, nothing replayed or re-announced) and the restarted instance
      closed the group 150 s after its last event ended, as the rule says. **Not verified:** the real events producer
      (P3-D4 does not exist yet — events were produced from the fixtures), the api topology endpoint live, a second replica.
      Found on the way: tests caught that `ON DELETE SET NULL` on `merged_into` contradicts the table's own CHECK (now
      CASCADE); UUIDv7 ids are not ordered within one millisecond, so the survivor is chosen by creation time; link rows
      came back in random order after a reload, so the message order is now canonical.

### P3-J3 · Alerts backend & notifier plugins — 5 pts · Must · E08 · FR-ALR-01…03
- [x] API consumer for `event.v1`, `correlation.v1` creates/updates `core.alerts` per severity threshold.
- [x] `WS /api/v1/ws` with JWT auth, role filtering, message types per design §9; Redis pub/sub fan-out (works with 2 API replicas).
- [x] Ack/resolve endpoints with notes + audit log.
- [x] `Notifier` interface with `DashboardNotifier` (on) and `EmailNotifier`, `TelegramNotifier` (implemented, disabled by default via `VMS_NOTIFY_CHANNELS`).

### P3-J4 · Alerts & events UI — 3 pts · Must · E08 · FR-ALR-01, FR-ALR-02
- [x] Alert tray (AlertItem §B.7), live via WS, acknowledge/resolve with note dialog; `aria-live` per §B.10.
- [x] Events page with filters; event detail with keyframes, VLM caption, clip playback, correlated events list.
  - Scope note: the page lists events that raised an alert (`GET /alerts`); it switches to `GET /events` (every verified event) when P3-D4's `events.events` lands. See `frontend/README.md`.

### P3-J5 · Zone & camera-link editors — 3 pts · Must · E03 · FR-CAM-03, FR-CAM-04
- [x] Polygon editor over a camera snapshot (add/move/delete points, name, type, schedule).
  - Scope note: `GET /cameras/{id}/snapshot` (design §9) was never built, so the still is captured from the camera's live view in the browser; zones can only be drawn while the camera streams. See `frontend/README.md`.
- [x] Camera links editor (table + simple node diagram) for overlap/transit edges.

### P3-J6 · Caption & VQA annotation kit — 5 pts · Must · E10 · FR-RSN-03
- [x] `config/vqa_bank.yaml`: 5–8 questions per event type.
- [x] Label Studio template for per-phase, per-view caption + VQA verification.
  - Generated from the bank, one config per event type (`ml/annotation/caption_vqa/*.xml`); all six parse and validate with Label Studio's own `LabelInterface`. Not driven in a running Label Studio UI.
- [ ] Kaggle notebook generating draft captions/VQA answers with the largest open VLM that fits (e.g. Qwen2.5-VL-7B) on phase-labelled clips; drafts imported as pre-annotations.
  - Written (`ml/annotation/caption_vqa/prelabel_kaggle.ipynb`) and its pipeline run end to end with a placeholder model in the tests; **never run against Qwen2.5-VL-7B** (needs a Kaggle T4). Tick this once a real trial run on a few clips has produced drafts.
- [x] Converter → `phavr_labels.jsonl`; script reports pseudo-label edit rate after human verification.
  - Its input, `phase_labels.jsonl`, is the phase annotation kit's export (P3-D5), frozen as `phase_labels.v1`; the converter's output is checked against J6's reader in a test.

---

# Phase 4 — Multimodal search (weeks 7–8)

**Goal / demo:** implicit text query and image query return ranked clips with reasoning traces and masks; first retrieval benchmark numbers.

**Contracts frozen day 1:** `queryplan.v1`, `candidate.v1`, search response, grounding + image-search response.

**Support track:** K & P write ≥ 150 benchmark queries with ground truth (by end of week 8); annotation continues.

## Divyansh — 23 pts

### P4-D1 · Retrieval service & query decomposition — 5 pts · Must · E11 · FR-SRC-01, FR-SRC-02
> **2026-10-08:** 30 golden queries (20 vocabulary, 10 replaying what `qwen2.5:3b` really answered; `services/retrieval/tests/unit/test_golden_queries.py`). They found three planner bugs, fixed: a model that lists every area it was shown became a zone filter, event words matched inside other words (`ran` in *entrance* and *orange*), and *after dark* became the colour black.
> **Status 2026-10-04 — partly built** (`services/retrieval`): `POST /search` with `fast`/`reason`, plan from the keyword vocabulary or `query_decompose/1.0` (categories mapped to the detector's, times from the text), search log. **Not done:** the 30 golden query → plan tests with `FakeGateway` recordings.
- [x] `services/retrieval` FastAPI app; `POST /search` accepts query, filters, `mode=fast|reason`.
- [x] Prompt `query_decompose/1.0` → `QueryPlan` validated; relative times resolved with site timezone; filters from request override plan.
- [x] 30 golden query → plan tests (with `FakeGateway` recordings) covering attributes, time, zones, implicit actions.

### P4-D2 · Coarse hybrid retrieval — 8 pts · Must · E11 · FR-SRC-03, FR-SRC-10
> **Status 2026-10-04 — partly built:** SigLIP 2 text encoder on CPU, `frames` + `tracks` search with plan filters, RRF, 10 s windows, per-stage timings. `knowledge` (dense + BM25) is searched and fused with Postgres full-text on captions. `mode=fast` measured at p95 0.25 s (30 fresh queries, `ml/evaluation/results/p7-latency.md`). The `mode=fast` p95 ≤ 1 s criterion is met.
- [x] SigLIP 2 text encoder on CPU; visual queries against `frames` and `tracks` with payload filters from the plan.
- [x] Dense + sparse search on `knowledge` (event captions) for text queries.
- [ ] Reciprocal rank fusion; grouping hits into segment-window candidates (merge within 10 s per camera); top-K = 30.
- [x] `mode=fast` returns in p95 ≤ 1 s on the Phase 2 archive (measured).
- [x] Per-stage timings included in response for logging.

### P4-D3 · LLM reasoning rerank & traces — 5 pts · Must · E11 · FR-SRC-04
> **Status 2026-10-04 — partly built:** twin excerpts, batched rerank (5 per call, top 10), score + ≤ 60-word trace + `missing[]`, weighted blend. **Not done:** emitting `candidate.v1` to JIT (nothing consumes `missing[]` yet), reasoning weights read from config rather than settings.
- [x] Loads twin excerpts (only matched tracks ± context, token-capped) for candidates; batched prompts (5 candidates/call).
- [x] Output per candidate: score 0–1, trace ≤ 60 words, `missing[]` sub-questions; validated with retry.
- [ ] Final ranking = weighted fused + reasoning score; weights configurable; emits `candidate.v1` to JIT for top-N with `missing`.

### P4-D4 · Search UI — 5 pts · Must · E11 · FR-SRC-01, FR-SRC-08
> **Status 2026-10-04 — built, driven in a real browser (Brave) for fast and reason mode:** query bar, camera/time filters, fast/reason toggle, result cards with the collapsible trace, "Open in playback" at the result's time (Playback now honours `?camera=&start=&end=`), fast results first then the reasoned ranking, empty/error states. No component tests were written.
- [x] Search page: query bar with example placeholder, camera/time filter chips, fast/reason toggle.
- [x] Result cards: keyframe, camera, time, score, collapsible ReasoningTrace (§B.7), "Open in playback" at exact timestamp.
- [x] Progressive rendering: fast results first, reasoned ranking replaces them when ready.
- [x] Empty/error states per §B.8.

## Jatin — 23 pts

### P4-J1 · Image query path — 2 pts · Must · E11 · FR-SRC-06
> **Status 2026-10-04 — partly built:** `POST /search/image` takes an upload (SigLIP 2 vision on CPU, `tracks`); the UI has *Search by image*. **Not done:** `{frame_uri, bbox}` crops and the "Find similar" tool on a paused frame.
- [ ] `POST /search/image` accepts upload or `{frame_uri, bbox}`; crops, embeds with SigLIP 2 vision (CPU), searches `tracks` with filters.
- [ ] Results grouped by track, sorted by score then time, same response shape as text search.

### P4-J2 · Object-level grounding — 5 pts · Must · E11 · FR-SRC-07
> **Status 2026-10-04 — partly built, in retrieval rather than perception:** `POST /search/grounding` (api proxy) turns `(search_id, result_id)` into SAM 2.1-tiny masks of the objects the result matched, run-length encoded, cached in `vms-masks`. It runs on **CPU in the retrieval process** (~1.2 s warm, so the p95 ≤ 700 ms target is not met; the GPU stays free for the language models).
- [ ] `perception/grounding` module: `POST /internal/grounding {keyframe_uri, bbox}` → SAM 2.1-tiny mask → RLE cached in `vms-masks`.
- [ ] Shares the perception process/GPU; loads lazily; p95 ≤ 700 ms warm (measured).
- [ ] API `POST /search/grounding` proxies with caching by `(keyframe_uri, bbox)`.

### P4-J3 · JIT refinement — 5 pts · Must · E11 · FR-SRC-05
> **Status 2026-10-04 — partly built (opt-in):** with `jit: true` the rerank's yes/no questions about missing facts are put to `jit_vqa` on the result's keyframe (≤ 3 results × 2 questions, 150 s budget), cached in `retrieval.jit_cache` (migration 0013), and fed back to a rescoring pass; the UI shows them as "Checked in the picture". **Not done:** consuming `candidate.v1`, indexing answers into `knowledge`, the 8 s default budget (a text→vision model swap alone is ~20 s here); some vision replies come back empty and are skipped.
- [ ] Consumes `candidate.v1` with `missing[]`; asks `jit_vqa` on candidate keyframes; answers stored in `retrieval.jit_cache` keyed by `(segment_id, question_hash)`.
- [ ] Returns answers to the rerank stage; time budget per search (default 8 s), skipped gracefully when exceeded.
- [ ] Answers also indexed into `knowledge` (doc_type `jit_answer`) so later searches benefit.

### P4-J4 · Search API, logging & event-caption indexing — 3 pts · Must · E11 · FR-SRC-09
> **Status 2026-10-04 — partly built:** the api proxies `/search*` with auth, presigned urls and timeouts; `retrieval.search_logs` is written. Event captions are indexed into `knowledge` by the indexer (see P6-J3).
- [x] API proxies `/search*` to retrieval with auth and timeouts.
- [ ] `retrieval.search_logs` stores query, plan, candidates, final results, per-stage latency, profile.
- [x] Indexer consumes `event.v1` and writes captions into `knowledge` (dense + sparse) with payload.

### P4-J5 · Image search & mask UI — 3 pts · Must · E11 · FR-SRC-06, FR-SRC-07
- [ ] "Search by image" upload dialog and "Find similar" crop tool on any paused frame (playback, event detail).
- [ ] Mask overlay rendering on result keyframes, requested lazily when a card is visible.

### P4-J6 · Retrieval evaluation harness — 5 pts · Must · E18 · EV-01
- [ ] `ml/evaluation/retrieval`: `queries.jsonl` format + validation; ground-truth labelling guide for K & P.
- [ ] Metrics R@1/5/10, mAP, tIoU@0.3/0.5, latency per stage.
- [ ] Ablation runner: `embed`, `embed+filters`, `+rerank`, `+jit`, for `local` and `hybrid` profiles.
- [ ] Baseline report generated on the first 50 queries.
      Not ticked. A first harness exists with labels nobody had to annotate: `ml/evaluation/retrieval` joins the 121
      labelled MEVA example clips (36 activities) into one recorded stream and scores 36 plain-language queries by
      whether the returned windows overlap a clip of that activity (results:
      `ml/evaluation/results/meva-retrieval-benchmark.md`). Fast mode finds a relevant window at rank 1 for 5 of 36
      queries and in the top 10 for 20 (random: ~1 and ~9); reason mode 8 and 24 at ~70× the latency (better on 12
      queries, worse on 7). What is still missing here: the `queries.jsonl` format and labelling guide, ≥ 150 queries
      with half implicit, mAP/tIoU, filters/JIT ablations and the `hybrid` profile. The MEVA queries are one clean
      activity name each, and clips of one activity often share a scene, so the numbers are a ceiling.

---

# Phase 5 — Phase-aware event reasoning (weeks 9–10)

**Goal / demo:** click *Analyze* on a correlated incident → phase timeline across views with per-phase captions/VQA; fine-tuned vs zero-shot numbers.

**Contracts frozen day 1:** `phasetimeline.v1`, `evidence.v1`, `incident.v1`, `incidentready.v1`.

**Dependency:** ≥ 150 phase-annotated clips by start of week 9 (minimum viable), target 250 by end of week 9.

## Divyansh — 22 pts

### P5-D1 · TG dataset builder — 3 pts · Must · E12
- [x] `phase_labels.jsonl` → instruction JSONL: ≤ 16 timestamped frames (≤ 360 p) + prompt → phase JSON target.
- [x] Multi-view samples include all views with camera tags; split 70/15/15 **by source video**; manifest + hash committed.
- [x] Frames + JSONL packaged as a Kaggle dataset.
      > **Status 2026-10-06 — builder written, never run on real labels** (`ml/training/tg/`, README there): `phase_labels.v1`
      > validated with the annotation kit's schema; one sample per clip × camera, frames ≤ 360 p, the `phase_tg` 1.0 prompt
      > rendered like `services/reasoning` does (a test runs the service's `locate_phases` and requires the same prompt),
      > split by source video 70/15/15 in a shared, extend-only `splits.json`, `manifest.json` with prompt and file hashes,
      > `dataset-metadata.json` for Kaggle. 16 unit tests on synthetic videos (five deliberate bugs caught), run in CI.
      > **Differs from the story text on purpose:** 5–8 frames per sample, not ≤ 16 (the service shows at most 8), and the
      > answer is one stage per frame (what `FrameLabels` parses), not spans; all views of a clip in one sample is not built.
      > Nothing has been uploaded to Kaggle: there are no phase annotations yet.

### P5-D2 · TG adapter fine-tuning — 8 pts · Must · E12
- [ ] Unsloth QLoRA notebook on Qwen2.5-VL-3B with hyperparameters from design §8.3; runs within one Kaggle session (checkpointing to resume).
- [ ] Experiment tracking (config, loss curves, val mIoU per epoch).
- [ ] Best adapter uploaded to `vms-models/tg/v1` with model card (data, metrics, limits).

### P5-D3 · TG evaluation — 3 pts · Must · E18 · EV-02
- [x] `ml/evaluation/reasoning/phase`: mIoU and boundary MAE on test split.
- [ ] Baselines: zero-shot base 3B (same prompt) and zero-shot cloud VLM on ≤ 40 clips (free tier).
- [ ] Error analysis: confusion between adjacent phases, per event type, single vs multi-view.
      > **Status 2026-10-06 — harness written, no real result** (`ml/evaluation/reasoning/phase/`, README there): mIoU,
      > boundary error, frame accuracy and usable-answer rate with 95 % bootstrap intervals, by event type and single/multi-view;
      > methods `rules` (the service's detector-timing fallback) and `model` (any `phase_tg` gateway task, same fallback). 13
      > unit tests. Run once against the real zero-shot `qwen2.5vl:3b` on synthetic clips as a plumbing check only. **Not done:**
      > the baselines on real clips (no annotations yet), the cloud-VLM baseline, the confusion matrix between adjacent phases.

### P5-D4 · Reasoning orchestrator — 5 pts · Must · E12 · FR-RSN-01, FR-RSN-04…06
> **Status 2026-10-04 — partly built** (`services/reasoning`): `reasoning.jobs` queue with `SKIP LOCKED` and lease recovery, auto-queue from closed `correlation.v1` groups (high+, capped per hour) and `POST /events/{id}/analyze`, ±15 s window, TG → evidence → synthesis, queue position and stage in the job. Phase location uses the **zero-shot base model** (no adapter is trained), falling back to detector timing, recorded in provenance. **Not done:** `job.progress` on the WebSocket (the UI polls), the cloud fallback step.
- [x] Consumes `correlation.v1` (closed, severity ≥ threshold) and `POST /events/{id}/analyze`; `reasoning.jobs` queue with `SKIP LOCKED`.
- [x] Gathers synced clips for all cameras (window ±15 s), samples frames, runs TG → `phasetimeline.v1` → calls evidence module → stores bundle.
- [ ] Job progress via API WS `job.progress`; queue position exposed.
- [ ] Fallback chain: TG adapter → zero-shot base → cloud profile, recorded in provenance.

### P5-D5 · Adapter serving (`hf_local`) — 3 pts · Must · E12
> **2026-10-08 — backend built, verified on a tiny model only:** `llm/hf_local.py` (see design §8.3): base loaded once, adapters fetched and hot-swapped, frame back-off on out-of-memory, error translation, wired into the gateway when a profile uses `hf_local`. 22 unit tests with a fake runtime (mutation-checked) and a real run with a 10 M-parameter random Qwen2.5-VL through the real transformers, PEFT and bitsandbytes code in fp16 and 4-bit (base loaded once; plain, `tg` and `phavr` outputs differ and repeat; VRAM released on unload). **Not measured:** VRAM and latency of the real 3B model (download too slow here) and quality of any adapter (none trained).
- [x] Gateway provider loads 4-bit base once and hot-swaps `tg` / `phavr` LoRA adapters via PEFT under the GPU lease.
- [x] Pixel/frame caps configurable; OOM caught → retry with fewer frames.
- [ ] Measured VRAM and latency per call documented.

## Jatin — 22 pts

### P5-J1 · PhaVR dataset builder — 3 pts · Must · E12
- [x] `phavr_labels.jsonl` → instruction JSONL for captioning and VQA tasks per phase × view (≤ 8 frames).
- [x] Same video-level split as TG (shared manifest); packaged as a Kaggle dataset.
      > **Status 2026-10-06 — builder written, never run on real labels** (`ml/training/phavr/`, README there): reads
      > `phavr_label.v1` plus the phase labels (for video locations); 2–4 frames per phase × view (the service's cap), the
      > `phase_vr` 1.0 prompt and the VQA bank rendered as `services/reasoning` does (a test runs the service's real
      > `read_view` and requires the same prompt), canonical answers, skip-and-list for anything unusable; shares the TG
      > builder's extend-only `splits.json` so both adapters have the same train/val/test videos. 10 tests on synthetic
      > videos, run in CI. **Differs from the story text:** ≤ 4 frames, not ≤ 8 (the service shows at most 4). Not packaged
      > or uploaded: there are no labels yet.

### P5-J2 · PhaVR adapter fine-tuning — 8 pts · Must · E12
- [ ] Unsloth QLoRA notebook (same base/hyperparameters), mixed caption + VQA batches.
- [ ] Experiment tracking; best adapter to `vms-models/phavr/v1` with model card.

### P5-J3 · PhaVR evaluation — 3 pts · Must · E18 · EV-02
- [x] BLEU-4, METEOR, ROUGE-L, CIDEr for captions; exact/normalized-match accuracy for VQA, per view type.
- [ ] Baselines: zero-shot base 3B and cloud VLM subset; results table + qualitative examples.
      > **Status 2026-10-06 — harness written, no real result** (`ml/evaluation/reasoning/phavr/`, README there): BLEU-4,
      > CIDEr-D, ROUGE-L, a METEOR variant (`meteor_exact`: identical words only, **not** the published METEOR, which needs
      > downloads) and VQA accuracy with 95 % intervals, by stage and primary/other view; methods `template` (no model) and
      > `model` (any `phase_vr` gateway task, cleaned with the service's own `clean_answers`). 18 tests. A plumbing run against
      > the real zero-shot model found that the service dropped most VQA answers (the model copies the prompt's `[id]`
      > brackets); fixed in `services/reasoning` with tests. **Not done:** results on real labels, the cloud baseline,
      > qualitative examples.

### P5-J4 · Evidence builder — 5 pts · Must · E12 · FR-RSN-03, FR-RSN-04
> **Status 2026-10-04 — built inside `services/reasoning` by Track D** at the user's request: per phase × camera frames, caption + VQA-bank questions, stable ids, frames copied to `vms-evidence`, `evidence.v1`. Uses the zero-shot base model, not PhaVR.
- [ ] `reasoning/evidence`: for each phase × view, sample frames, run PhaVR caption + VQA bank for the event type.
- [x] Assemble `evidence.v1` with stable evidence ids and frame URIs in `vms-evidence`; validated against contract.
- [ ] Skips empty phases/views; per-call timings in provenance.

### P5-J5 · Event reasoning view — 3 pts · Must · E12
> **2026-10-08:** the report page and the event page's Reasoning section (*Watch the views together*) now have the phase band, a lane per camera with the phases and one playhead, and the incident's cameras on one playhead; pressing a phase plays every view for that phase from its start and stops at its end (driven in Brave on a fresh incident: playhead jumped to the phase start, stopped at its end, largest drift 145 ms). Phases are located once, on the primary view, so every lane shows the same spans; the incident above had a single camera, so four-camera phase playback was checked on the timeline page, not on an incident.
> **Status 2026-10-04 — partly built:** the reasoning view is the incident report (phase band, per-phase captions and Q&A, evidence frames) and the event page's *Reasoning* panel with job progress and queue position. **Not done:** camera lanes and synced multi-view playback per phase.
- [ ] Event/correlation detail gains a "Reasoning" tab: timeline with phase band across camera lanes (§B.6), per-phase captions and Q&A, evidence frames.
- [x] Clicking a phase plays all views for that phase in sync (≤ 4 views); job progress/queue shown while running.

---

# Phase 6 — Incident reports, assistant, daily reports, investigation (weeks 11–12)

**Goal / demo (feature complete):** incident report with causal chain + PDF; multi-turn assistant with citations; daily report PDF; investigation timeline with saved case.

**Contracts frozen day 1:** assistant tool endpoints (events/incidents/timeline query APIs), daily facts schema.

## Divyansh — 23 pts

### P6-D1 · Incident report synthesis — 8 pts · Must · E13 · FR-INC-01…03
> **2026-10-08:** golden tests on five real evidence bundles (`services/reasoning/tests/unit/test_incident_synthesis.py`, fixtures from stored incidents): schema-valid, citations valid, an invented id quoted back and corrected, an uncited claim dropped, a model that is down failing with its reason. Mutation-checked.
> **Status 2026-10-04 — partly built:** two schema-validated steps (stage summaries; causal chain, factors, actions) with citation checks, ≤ 2 retries quoting the problems, uncited claims dropped (never patched), `failed` with the raw output kept; `reasoning.incidents` + `incidentready.v1`. **Not done:** golden tests on 5 fixture bundles, S3 copy of the report, WS `incident.ready`.
- [x] Hierarchical prompts: phase summaries → causal chain & contributing factors → final report, each schema-validated.
- [x] Citation validator (every evidence id exists; each causal step and factor has ≥ 1); retry with error text ≤ 2; `failed` status with raw output.
- [ ] Persists `reasoning.incidents` (JSONB + S3 copy), publishes `incidentready.v1`, WS `incident.ready`.
- [x] Golden tests on 5 fixture evidence bundles (schema-valid, citations valid).

### P6-D2 · RAG assistant agent & streaming — 8 pts · Must · E14 · FR-AST-02…04, FR-AST-06
> **2026-10-08:** 25+ scripted conversations (`tests/unit/test_assistant.py`): the lookup each question gets, whole turns with a scripted model, citations resolved server-side, unknown tags reported, a repeated lookup stopped. They found that *daily security report* was not routed (fixed).
> **Status 2026-10-04 — partly built** (`services/retrieval/src/retrieval/assistant`): seven parameterised tools (`search_footage`, `list_events`, `list_incidents`, `get_incident`, `get_timeline`, `count_objects` over `vision.minute_counts`, `get_daily_report`); SSE `tool_call`, `tool_result`, `token`, `citation`, `done`, `error`; citation tags resolved server-side. The local model has no native tool calling, so clear questions are routed by keywords and only the rest go to a JSON-action planner (≤ 4 calls). **Not done:** the 25 scripted `FakeGateway` conversations, `zone` in `count_objects` (counts are per camera), a rate/size cap on tool results beyond truncation.
- [x] Tools per design §10.3 with JSON schemas; `count_objects` uses pre-defined parameterized SQL only.
- [ ] Agent loop (≤ 5 tool rounds), citation format enforcement, "nothing found" behaviour.
- [x] `POST /assistant/sessions/{id}/messages` streams SSE events `token`, `tool_call`, `tool_result`, `citation`, `done`, `error`.
- [x] 25 scripted conversations pass tool-selection and citation checks with `FakeGateway` recordings.

### P6-D3 · Conversation memory — 2 pts · Should · E14 · FR-AST-01, FR-AST-05
> **2026-10-08:** memory is now unit-tested (`tests/unit/test_assistant.py`): the 12-message window, the rolling summary, tool output cut to its budget.
> **Status 2026-10-04 — built, not unit-tested end to end:** sessions and messages in `retrieval.chat_sessions` / `chat_messages` (migration 0010), last 12 messages verbatim plus a rolling summary updated in the background, tool output truncated.
- [x] Sessions/messages persisted; last 12 messages + rolling summary; tool results truncated to budget.

### P6-D4 · Assistant UI — 5 pts · Must · E14 · FR-AST-01, FR-AST-03
> **Status 2026-10-04 — built, driven in a real browser:** conversation list, streaming chat, tool activity with what each lookup found, citation chips (event → its alert page, incident → report, footage → playback at the moment), starter questions from the last 24 h, stop button, retry. Records the model did not cite are shown as "Records consulted", never as its citations.
- [x] Session list + chat column (§B.7); streaming render; tool activity lines; EvidenceChip citations opening clips/incidents.
- [x] Suggested starter questions from the last 24 h; stop-generation button; error/retry states.

## Jatin — 23 pts

### P6-J1 · Daily security report job — 5 pts · Must · E15 · FR-RPT-01…04
> **Status 2026-10-04 — partly built** (`services/reasoning/src/reasoning/reports`): `DailyFacts` from fixed SQL, narrative from `daily_narrative/1.0` with every number checked against the figures (one retry, then a template text; `narrative_source` says which), `reasoning.daily_reports` (migration 0011), the worker queues yesterday's report after 06:00 IST, `POST /reports/daily` (≤ 7 days) and `python -m reasoning.reports.daily`. **Not done:** server-side charts and PDF (WeasyPrint; the UI draws the charts and the browser prints to PDF), indexing into `knowledge`, supercronic in Compose (the worker schedules it).
- [ ] `DailyFacts` aggregation SQL; charts (events by hour/type/camera, alert response times).
- [x] Narrative via gateway with numeric post-check (numbers must exist in facts) → regenerate once → template fallback.
- [ ] Jinja2 + WeasyPrint PDF per §B.11 → `vms-reports`; row in `reasoning.daily_reports`; indexed into `knowledge`.
- [ ] Entry point `python -m reasoning.reports.daily`; supercronic in Compose; `POST /reports/daily` on demand (≤ 7-day range).

### P6-J2 · Incident UI & PDF export — 5 pts · Must · E13 · FR-INC-04, FR-INC-06
> **Status 2026-10-04 — partly built:** incidents list (severity filter) and report view with evidence chips, provenance note, notes and reviewed/closed. **Not done:** server-side PDF (the page offers print-to-PDF).
- [x] Incidents list (filters, severity, status) and report view per §B.7 with EvidenceChips and ProvenanceNote.
- [ ] Status/notes editing (operator+); incident PDF via the same PDF pipeline.

### P6-J3 · Incident indexing & similar incidents — 3 pts · Should · E13 · FR-INC-05
> **Status 2026-10-04 — partly built:** the indexer writes event captions and incident-report sections to `knowledge` (dense bge-small + BM25, `vms_common.qdrant.knowledge`), search fuses them, and `GET /incidents/{id}/similar` returns up to 5 other reports (same event type boosted) shown on the report page. **Not done:** the assistant tool endpoints exposed per the frozen contract as a separate service API.
- [x] Indexer consumes `incidentready.v1`, indexes report sections into `knowledge`.
- [x] `GET /incidents/{id}/similar` returns ≤ 5 by hybrid similarity + same event type boost; shown in UI.
- [ ] Assistant tool endpoints for events/incidents/timeline exposed per frozen contract.

### P6-J4 · Investigation timeline & cases — 8 pts · Should · E16 · FR-INV-01…03
> **2026-10-08:** synchronized playback built (`features/playback/components/SyncedPlayer.jsx`, `lib/sync.js`): up to four cameras on one playhead, a camera with no recording at that moment says so and waits, the playhead holds while any camera with footage buffers, small drift is closed by running a picture 5-10 % slow or fast and a drift past 300 ms by a seek. On the timeline page a selected period (up to 30 min) plays all cameras together. Unit and component tests (mutation-checked). **Measured in Brave with three real MEVA cameras** (22 fragments each, no failed requests): steady state within about 25 ms of the playhead by the player's own fragment table, a transient of 110-170 ms at each 10 s segment boundary that the nudging closes within about 1.3 s; the largest value seen at start-up before nudging existed was 449 ms. **Not verified:** that the *pictures* line up in content (the clips carry no visible clock, and a parse of the playlist that does not use hls.js's corrected fragment times disagreed by up to 450 ms, which I attribute, unproven, to declared versus real segment durations). Still not built: *Search in range*.
> **Status 2026-10-04 — partly built:** cases (`core.cases`, `core.case_items`, migration 0012; API; Cases pages; *Save to case* from search results, events, incident reports and timeline selections) and a per-camera timeline of events and incident reports with drag-to-select, zoom and save. **Not done:** synchronised playback of up to 4 cameras from one playhead, "Search in range", the 300 ms drift measurement. The demo has one real camera.
- [ ] Multi-camera timeline (lanes, events, correlation links, incidents) for a selected range.
- [x] Synchronized playback of up to 4 cameras driven by one playhead (drift ≤ 300 ms).
- [ ] Shift-drag range → "Search in range" / "Save to case"; cases CRUD with bookmarked items and notes.

### P6-J5 · Daily reports UI — 2 pts · Must · E15 · FR-RPT-02, FR-RPT-04
> **Status 2026-10-04 — built, driven in a real browser:** reports list with live status, *Generate report* dialog (date range, ≤ 7 days), report page with the narrative, tiles, hourly chart, breakdowns, response times and the incident list, print-to-PDF.
- [ ] Reports list, "Generate report" dialog (date range), status while generating, preview + download PDF.

---

# Phase 7 — Kubernetes, cloud, observability, evaluation, hardening (weeks 13–14)

**Goal / final demo:** whole system on minikube (local) and a cloud VM (Compose); Grafana dashboards; full evaluation report.

**Contracts frozen day 1:** infra service names/ports in k8s (`deploy/k8s/base/infra/SERVICES.md`).

**Support track:** K & P run usability study and response-quality human ratings; final documentation.

## Divyansh — 23 pts

### P7-D1 · Kubernetes infra layer — 5 pts · Must · E17 · NFR-POR-01
> **Status 2026-10-04 — manifests written, not deployed:** `deploy/k8s/` (kustomize base for infra, apps, migration and topic Jobs, ingress; minikube overlay) renders and passes `kubeconform -strict` for Kubernetes 1.31 (38 resources). No cluster was available, so nothing has been applied; `make k8s-up` / `k8s-down` / `k8s-render` exist. Plain StatefulSets instead of Strimzi/CloudNativePG/Helm, one namespace instead of three (see `deploy/k8s/README.md`). **Not done:** the minikube setup script with `--gpus all`, any run on a cluster.
- [ ] minikube setup script (docker driver, addons, `--gpus all` attempt).
- [ ] Strimzi Kafka (KRaft) + topics as `KafkaTopic` resources; CloudNativePG cluster; Qdrant Helm; Redis; object storage; MediaMTX (NodePort RTSP).
- [ ] Namespaces, PVCs, resource requests sized for a 16 GB laptop; `SERVICES.md` published.

### P7-D2 · GPU scheduling in Kubernetes — 5 pts · Must · E17
> **Status 2026-10-07 — manifests written, never applied (no cluster, no GPU node here):** `deploy/k8s/overlays/gpu` (perception and an in-cluster Ollama with a PVC and a model-pull Job both ask for `nvidia.com/gpu: 1` and are placed by `vms.io/gpu-role` = `perception` / `genai` / `shared`; a `shared` single GPU needs the device plugin's time-slicing, which shares the card but not its VRAM) and `overlays/host-gpu` (the fallback: Ollama stays on a host machine and pods reach it as the Service `ollama` with an Endpoints, or `ExternalName`; perception is off there). `make k8s-check` renders all three overlays, passes `kubeconform -strict`, asserts what each is for, and was mutation-checked. Reasoning does not request a GPU: it calls Ollama (it would only with in-process `hf_local` adapters, which do not exist). Perception on a host cannot reach the cluster's Kafka (in-cluster advertised name), so that direction is **not built**. "Tested" fallback is therefore render-tested only.
- [ ] NVIDIA device plugin; `vms.io/gpu-role` node labels; perception/reasoning request `nvidia.com/gpu`.
- [ ] Documented, tested fallback: GPU services on host Compose exposed to the cluster via `ExternalName`/Endpoints.

### P7-D3 · Observability — 5 pts · Should · E17 · NFR-OBS-01, NFR-OBS-02
> **Status 2026-10-08 — mostly built:** the missing series are in (`vms_kafka_consumer_lag`, `vms_kafka_dlq_total`, `vms_gpu_memory_bytes`, and `vms_http_request_seconds` for the api and retrieval, which had no request metrics at all); nine alert rules tested with `promtool test rules` and mutation-checked (`make obs-test`, CI job `obs-rules`); the dashboard has 22 panels (lag, dead letters, GPU memory, ingestion per camera, HTTP rate/errors/latency, firing alerts) with every query parsed; `deploy/k8s/obs/` (PodMonitors, generated PrometheusRule, dashboard ConfigMap, chart values rendered with the real chart). Lag was checked against the live Kafka. **Not done:** `vms_stream_reconnects_total`, separate Pipeline/GenAI/API dashboards (one overview exists), a real install on a cluster, GPU gauge seen live only as a one-off read (perception was not running).
> **Status 2026-10-04 — partly built:** `vms_common.metrics.serve(port)` exposes the workers' metrics (ingestion 9101, perception 9102, indexer 9103, events 9104, correlation 9105, reasoning 9106; the api and retrieval serve `/metrics`); new series for search stages, assistant turns, reasoning stages/outcomes/queue depth, indexer lag and perception latency; `obs` Compose profile with Prometheus and Grafana and a provisioned 14-panel dashboard (`deploy/compose/obs/`). **Not done:** `vms_kafka_consumer_lag`, `vms_gpu_memory_bytes` (needs an exporter), alert rules, the kube-prometheus-stack values.
- [ ] All metrics in design §15 exported; kube-prometheus-stack with ServiceMonitors (and Compose `obs` profile).
- [ ] Grafana dashboards: Pipeline health (lag, fps, segments), GenAI (latency/tokens per provider, queue depth), API (RPS, p95, errors).

### P7-D4 · Latency & throughput evaluation — 5 pts · Must · E18 · EV-04
> **Status 2026-10-04 — partly built:** `ml/evaluation/latency/measure.py` measures the running stack through its HTTP interfaces and the database; results in `ml/evaluation/results/p7-latency.md` (fast search p50 0.22 s / p95 0.25 s, reason search p50 15.6 s, cold object masks 1.3 s, assistant turn p50 2.1 s, daily report ~11 s; pipeline lag and reasoning-job figures are from a contended-GPU period and say so). **Not done:** the 2/4/6-camera sweep (one real camera exists), consumer-lag and GPU-utilisation columns, cloud-profile runs.
- [ ] `ml/evaluation/latency` harness drives 2/4/6 cameras for 30 min per profile (local/hybrid/cloud).
- [ ] Measures NFR-PERF-01…05 p50/p95 from metrics + logs; results JSON + Markdown summary.

### P7-D5 · Resilience tests — 3 pts · Must · E17 · NFR-REL-01…04
> **2026-10-08:** all 428 integration tests were run for the first time since they were written (api 319, correlation/events/indexer 84, migrations and lease 22, plus the Kafka consumer pair): two had never passed (the DLQ header lookup, P1-D2, and a claim-timing test that depended on how soon after import it ran) and are fixed. CI has a new non-gating `integration` job.
> **Status 2026-10-04 — partly built, run on the stack:** `python -m vms_common.kafka.dlq_replay` (list, filter by topic, dry run, limit; unit-tested planning); `ml/evaluation/resilience/chaos.py` restarted the indexer, events and correlation five times in 7 minutes while footage flowed — 42 segments, 839/839 frame points and 1,403/1,403 track points in Qdrant, no sequence gap, no missing twin, no event in two groups (`ml/evaluation/results/p7-resilience.md`); `llm_down.py` shows every GenAI feature degrading with Ollama stopped — fast search unaffected, reason search falls back with a note, the assistant says the model is unavailable, the daily report uses its template, an analysis job fails with a reason, the gate holds candidates with back-off and drops none (`p7-degradation.md`). The harness also found a real bug: ingestion's ffmpeg segmenter had no input timeout, so a publisher that stopped sending without closing its connection left it blocked forever and recording stopped silently; fixed (socket timeout + no-progress watchdog, verified with a frozen publisher: reconnects in 13 s, recording resumes in 26 s). **Not done:** restarting the recorder and perception under load, pod-kill runs on Kubernetes.
> **2026-10-08:** the degradation is now also pinned by unit tests (phase location falls back to the detector's timing, an unreadable view is left out, a report step with the model down fails with its reason; golden synthesis tests on five real evidence bundles). The chaos script restarts the three consumers only; ingestion, reasoning, retrieval and the api are not restarted by it, so the first item stays open.
- [ ] Chaos script restarts each worker mid-stream; verifies zero missing segments/events and no duplicates.
- [x] DLQ replay tool; GPU/LLM-down scenario shows graceful degradation.

## Jatin — 23 pts

### P7-J1 · Kubernetes app layer — 5 pts · Must · E17 · NFR-POR-01
> **Status 2026-10-07:** the base and `minikube` overlay (rendered, schema-checked, never applied) plus an HPA on the indexer (`base/apps/indexer-hpa.yaml`, 1–3 on CPU, needs metrics-server). **The daily-report CronJob is deliberately not built:** the reasoning worker already queues yesterday's report itself after `daily_report_hour` and skips a day already scheduled, so a CronJob would duplicate it. `make k8s-up` has never been run.
- [ ] Kustomize base + `minikube` overlay: Deployments/Services for all app services and frontend, ConfigMaps (models/rules/correlation), Secret generator, probes.
- [ ] ingress-nginx routes (`/`, `/api`), migrations `Job`, daily report `CronJob`, HPA on indexer.
- [ ] `make k8s-up` brings the full app up on minikube.

### P7-J2 · Cloud Docker deployment — 5 pts · Must · E17
> **Status 2026-10-07 — written and partly verified, not deployed:** `deploy/compose/docker-compose.prod.yml` (GHCR images, Caddy, no host ports but 80/443/8189-udp, `cloud` profile, required secrets), `Caddyfile`, `.env.prod.example`, `update.sh` (pull, migrate, topics, start, `--status`, `--rollback`) and the runbook in `deploy/compose/README.md`. The `cloud` profile now sends `phase_tg` / `phase_vr` to Gemini too (the VM has no Ollama). Verified: config render and required variables, the Caddyfile and nginx in a real browser (no CSP violations; WHEP and HLS redirects fixed after the test found the HLS 302 lost its prefix), `update.sh` against a stub `docker`, the migration command in the api image. **Not verified:** a real VM, certificates, the `media.` site, hls.js playback, WebRTC over NAT. **Perception does not run in the cloud** (GPU image); archive mode is described, not rehearsed.
- [ ] `docker-compose.prod.yml` with Caddy (TLS), `cloud` LLM profile, CPU perception (≤ 2 cameras) or pre-indexed archive mode.
- [ ] Deployed on a free/student-credit VM; runbook (provisioning, env, backups, update) in `deploy/compose/README.md`.

### P7-J3 · Continuous delivery — 3 pts · Must · E17
> **Status 2026-10-07 — workflows written, never run on GitHub:** `.github/workflows/release.yml` (buildx + QEMU, GHCR, semver + sha tags, amd64+arm64 for the light services, amd64 only for retrieval/reasoning, perception not built; tag or manual dispatch) and `deploy.yml` (manual dispatch, SSH with host-key checking, environment `production`, inputs through the environment); both pass `actionlint`. The push-to-main trigger is left off until a manual run has gone green.
- [ ] GitHub Actions builds multi-arch images on tags/main and pushes to GHCR with semver + sha tags.
- [ ] Manual-dispatch deploy workflow to the VM over SSH.

### P7-J4 · Response-quality evaluation — 5 pts · Must · E18 · EV-03
> **Status 2026-10-07 — harness built and run:** `ml/evaluation/response_quality` (72 questions, 21 incidents), results in `ml/evaluation/results/response-quality.md`, blind human sheet + rubric form in the run directories. Objective before/after on the assistant (router fixes + the camera list now including switched-off cameras): first lookup right 78 % → 100 %, camera used 28 % → 100 %, day used 0 % → 100 %, written tags matching no record 29 % → 18 %. The **3B judge (llama3.2:3b) is weak**: it names a problem for every answer, repeats its prompt's example in some, returns no per-citation judgements, and scored the two runs alike, so citation precision is checked by a model-free event-type/camera agreement check instead and the human sheet is what decides the judge's worth. **No person has filled the sheets yet.**
- [ ] `ml/evaluation/response_quality`: judge prompts (faithfulness, relevance, citation precision) using a different model family; 20 % human-verification sheet.
- [x] Incident report rubric (1–5 × accuracy, completeness, causality, actionability) forms + aggregation; schema-valid rate.
- [ ] Runs on ≥ 60 assistant questions and all test-set incidents; results summary.

### P7-J5 · Usability kit & security hardening — 5 pts · Must · E18, E17 · EV-05, NFR-SEC-*
> **Status 2026-10-07:** the usability kit is written (`ml/evaluation/usability`: SUS questionnaire, 4 task scripts, consent note, result templates, a tested scorer) — no sessions held. Security headers and a Content-Security-Policy now exist in `deploy/compose/Caddyfile` and were exercised in a real browser against the production build (no violations; see the compose README for what was substituted). Not done: presign-expiry check re-verified, and everything that needs the real domain.
> **Status 2026-10-04 — hardening partly built:** rate limiting on login / search / assistant / analyses & reports (Redis, 429 + `Retry-After`, fails open), security headers in the api and in the frontend's nginx, the role × endpoint matrix extended to the endpoints added since (166 matrix tests), `gitleaks` was already in pre-commit. **Not done:** the usability kit (SUS questionnaire, task scripts, consent note, results template — for K & P), Caddy and a Content-Security-Policy (needs the deployment's real origins).
- [x] SUS questionnaire, 4 task scripts, consent note and results template for K & P.
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
