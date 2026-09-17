# Track J — Jatin Bansal (1RV25MC044)

**Total: 161 story points** (Divyansh: 161). Full acceptance criteria are in `docs/backlog.md`; this file is your map of what you own, what you hand over and what you wait on.

## What you own

| Area | Paths |
|---|---|
| Platform API | `services/api` (auth, RBAC, CRUD, recordings, alerts, WS, BFF proxy, notifiers), `libs/vms_db` base + migrations for your tables |
| Frontend foundation | `frontend/` scaffold, app shell, tokens, live wall, playback, settings, alerts, events, incidents, investigation, reports, image search |
| Indexing | `services/indexer`, Qdrant collection bootstrap |
| Correlation | `services/correlation`, `config/correlation.yaml` |
| Search (image, grounding, JIT) | `services/retrieval/search/{image,jit}`, `services/perception/grounding` |
| Reasoning (evidence, reports) | `services/reasoning/{evidence,reports}`, PhaVR adapter (`ml/training/phavr`), `config/vqa_bank.yaml` |
| Delivery & quality | CI/CD, `deploy/compose` app + prod profiles, `deploy/k8s/base/{apps,jobs,ingress}`, retrieval/response-quality/usability evaluation |

**Résumé-level skills covered:** FastAPI auth/RBAC and WebSockets, HLS video delivery, vector indexing with Qdrant, event-stream correlation algorithms, SAM-based object grounding, QLoRA VLM fine-tuning (captioning + VQA), evidence pipelines, PDF report generation, complex React UIs (timeline, synced multi-view playback), Kubernetes manifests, CI/CD to GHCR, cloud deployment, IR/LLM evaluation methodology.

---

## Phase 1 — API, auth & dashboard shell · 24 pts · weeks 1–2

| Story | Title | Pts |
|---|---|---|
| P1-J1 | API service skeleton & database | 5 |
| P1-J2 | Authentication & RBAC | 5 |
| P1-J3 | Camera management API | 3 |
| P1-J4 | Frontend scaffold & app shell | 5 |
| P1-J5 | Live camera wall | 3 |
| P1-J6 | CI pipeline | 3 |

- **You provide:** `/internal/v1/cameras` + fixture (freeze day 1); OpenAPI; CI for everyone.
- **You consume:** MediaMTX URLs (Divyansh) — run MediaMTX alone with a looping test video until the simulator lands.
- **Phase II demo contribution:** login, camera management, 6-tile live wall with status dots.

## Phase 2 — Indexing & playback · 23 pts · weeks 3–4

| Story | Title | Pts |
|---|---|---|
| P2-J1 | Indexer service (Postgres) | 5 |
| P2-J2 | Qdrant collections & vector upserts | 3 |
| P2-J3 | Recordings API & HLS playlists | 5 |
| P2-J4 | Zones API | 2 |
| P2-J5 | Playback page (timeline scrubber v1) | 5 |
| P2-J6 | Detection overlay | 3 |

- **You provide:** zones internal API + fixture; Qdrant collections that Divyansh queries in P4.
- **You consume:** `twin.v1`, `twinready.v1`, `.npz` fixtures (Divyansh) — build the indexer and overlay entirely against fixtures.
- **Note:** the timeline scrubber is the product's signature component (style guide §B.6). Build it as a reusable component; it grows in P5 and P6.

## Phase 3 — Correlation, alerts & configuration UI · 23 pts · weeks 5–6

| Story | Title | Pts |
|---|---|---|
| P3-J1 | Camera links (topology) API | 2 |
| P3-J2 | Correlation service | 5 |
| P3-J3 | Alerts backend & notifier plugins (WS, email/Telegram disabled) | 5 |
| P3-J4 | Alerts & events UI | 3 |
| P3-J5 | Zone & camera-link editors | 3 |
| P3-J6 | Caption & VQA annotation kit (VQA bank, template, pseudo-label notebook) | 5 |

- **You provide:** `correlation.v1` + fixtures (Divyansh's orchestrator consumes it in P5).
- **You consume:** `event.v1` fixtures (Divyansh); `FakeGateway` for the pseudo-label pipeline design.
- **Hand-off to support track:** caption/VQA verification template ready by end of week 6.

## Phase 4 — Image search, grounding, JIT & retrieval evaluation · 23 pts · weeks 7–8

| Story | Title | Pts |
|---|---|---|
| P4-J1 | Image query path | 2 |
| P4-J2 | Object-level grounding (SAM 2.1-tiny) | 5 |
| P4-J3 | JIT refinement | 5 |
| P4-J4 | Search API, logging & event-caption indexing | 3 |
| P4-J5 | Image search & mask UI | 3 |
| P4-J6 | Retrieval evaluation harness | 5 |

- **You provide:** grounding + image-search response fixtures (Divyansh's search UI renders them).
- **You consume:** `candidate.v1`, `queryplan.v1`, search response fixtures (Divyansh).
- **Support track:** give Kuldeep & Pankaj the ground-truth labelling guide on day 2 so ≥ 150 queries exist by end of week 8.
- **Watch out:** grounding runs inside the perception process on node A — coordinate VRAM with Divyansh's P2-D6 numbers.

## Phase 5 — Phase-aware reasoning (PhaVR + evidence) · 22 pts · weeks 9–10

| Story | Title | Pts |
|---|---|---|
| P5-J1 | PhaVR dataset builder | 3 |
| P5-J2 | PhaVR adapter fine-tuning (Kaggle/Colab, Unsloth QLoRA) | 8 |
| P5-J3 | PhaVR evaluation (caption metrics, VQA accuracy, baselines) | 3 |
| P5-J4 | Evidence builder (`evidence.v1`) | 5 |
| P5-J5 | Event reasoning view (phase band, synced views) | 3 |

- **You provide:** `evidence.v1` + fixtures (freeze day 1; Divyansh's synthesis depends on it).
- **You consume:** `phasetimeline.v1` fixture (Divyansh); verified caption/VQA labels from the support track.
- **Coordinate:** use the **same video-level split manifest** as Divyansh's TG dataset. Use your own Kaggle account for GPU hours so both trainings run in parallel.

## Phase 6 — Reports, incidents UI & investigation · 23 pts · weeks 11–12

| Story | Title | Pts |
|---|---|---|
| P6-J1 | Daily security report job (facts, charts, narrative check, PDF, schedule) | 5 |
| P6-J2 | Incident UI & PDF export | 5 |
| P6-J3 | Incident indexing, similar incidents & assistant tool endpoints | 3 |
| P6-J4 | Investigation timeline & cases (synced multi-camera playback) | 8 |
| P6-J5 | Daily reports UI | 2 |

- **You provide:** events/incidents/timeline query endpoints for Divyansh's assistant tools (freeze OpenAPI day 1); `DailyFacts` schema.
- **You consume:** `incident.v1` / `incidentready.v1` fixtures (Divyansh).

## Phase 7 — Kubernetes apps, cloud, CD & quality evaluation · 23 pts · weeks 13–14

| Story | Title | Pts |
|---|---|---|
| P7-J1 | Kubernetes app layer (Kustomize, ingress, CronJob, HPA) | 5 |
| P7-J2 | Cloud Docker deployment (Caddy TLS, cloud profile, runbook) | 5 |
| P7-J3 | Continuous delivery (multi-arch GHCR, deploy workflow) | 3 |
| P7-J4 | Response-quality evaluation (judge + human rubric) | 5 |
| P7-J5 | Usability kit & security hardening | 5 |

- **You consume:** `deploy/k8s/base/infra/SERVICES.md` (Divyansh, day 1).
- **Final report sections you write:** API & security design, indexing & playback, correlation algorithm, image search & grounding, PhaVR results, reports pipeline, deployment & CI/CD, retrieval/response-quality/usability results.

---

## Your weekly rhythm

- **Mon:** read both tracks' stories for the week; confirm the fixtures you depend on are merged.
- **Daily:** small PRs to `main`; Divyansh reviews. Review his PRs within 24 h.
- **Fri:** 20-min joint demo on `make up`; update `backlog.md` checkboxes; hand evaluation tasks to Kuldeep/Pankaj.
