# Software Requirements Specification (SRS)

| | |
|---|---|
| **System** | GenAI-VMS |
| **Version** | 0.1 (kickoff draft) — 17 Sep 2026 |
| **Standard** | Loosely follows ISO/IEC/IEEE 29148 |
| **Related** | `PRD.md` (features F-xx), `design_architecture.md`, `backlog.md` (stories) |

---

## 1. Introduction

### 1.1 Purpose
Specifies the functional and non-functional requirements of GenAI-VMS precisely enough to design, implement, test and evaluate it. Kuldeep and Pankaj derive test cases directly from the requirement IDs here.

### 1.2 Scope
GenAI-VMS ingests live and replayed multi-camera video, builds a structured digital twin, detects and correlates events, supports multimodal search, performs phase-aware reasoning and generates incident reports, daily reports and conversational answers.

### 1.3 Definitions
See `context.md §8` (glossary). Keywords **shall** (mandatory), **should** (desirable), **may** (optional).

### 1.4 Requirement ID scheme
`FR-<MODULE>-<nn>` for functional, `NFR-<CATEGORY>-<nn>` for non-functional. Each requirement lists priority (M/S/C) and the PRD feature it traces to.

## 2. Overall description

### 2.1 Product perspective
A self-hosted system of containerized microservices communicating through Kafka (asynchronous pipeline) and HTTP (synchronous queries), backed by PostgreSQL, Qdrant, Redis and S3-compatible object storage, with a React web dashboard. See `design_architecture.md §2`.

### 2.2 User classes

| Role | Permissions |
|---|---|
| **Admin** | Everything, including users, cameras, zones, topology, system settings |
| **Operator** | Live wall, playback, alerts (ack/resolve), search, events, incidents, assistant, cases, reports (generate + view) |
| **Viewer** | Read-only: playback, search, incidents, reports, assistant |

### 2.3 Operating environment
- Dev: Windows 11 + WSL2 (Ubuntu) or Linux, Docker, NVIDIA GPU with 4 GB VRAM, ≥ 16 GB RAM recommended.
- Local demo: minikube (Kubernetes) on WSL2/Linux.
- Cloud: single Linux VM with Docker Compose (CPU; reasoning via cloud LLM profile).
- Browser: latest Chrome, Edge or Firefox.

### 2.4 Design constraints
- Backend in Python 3.11 / FastAPI; frontend in JavaScript (no TypeScript).
- Only free/open-source software and free-tier APIs.
- Only one heavy model may occupy a 4 GB GPU at a time (GPU lease).
- Kafka messages ≤ 1 MB; video bytes never travel through Kafka.

### 2.5 Assumptions
Cameras expose RTSP (H.264). Camera clocks are NTP-synced, or ingestion wall-clock time is used. Replayed datasets are started synchronously by the simulator.

## 3. Functional requirements

### 3.1 Authentication & users (F-01)
| ID | Requirement | Pri |
|---|---|---|
| FR-AUTH-01 | The system shall authenticate users by username/email and password and issue a JWT access token (15 min) and refresh token (7 days). | M |
| FR-AUTH-02 | Passwords shall be hashed with Argon2id. | M |
| FR-AUTH-03 | Every API endpoint except login/health shall enforce role-based access per §2.2. | M |
| FR-AUTH-04 | Admins shall create, deactivate and change roles of users. | M |
| FR-AUTH-05 | Internal service-to-service endpoints shall require a service token distinct from user JWTs. | M |
| FR-AUTH-06 | Login shall be rate-limited (5 failed attempts / 5 min per account). | S |

### 3.2 Camera, zone & topology management (F-02, F-09)
| ID | Requirement | Pri |
|---|---|---|
| FR-CAM-01 | Admins shall add, edit, disable and delete cameras with name, RTSP URL, site, location label and optional lat/long. | M |
| FR-CAM-02 | The system shall show each camera's status (online, reconnecting, offline) updated at least every 10 s. | M |
| FR-CAM-03 | Admins shall draw polygon zones on a camera snapshot, with name, type (generic/restricted/entrance/exit) and optional active schedule. | M |
| FR-CAM-04 | Admins shall define topology edges between cameras: `overlap` (tolerance seconds) or `transit` (min/max seconds, direction). | M |
| FR-CAM-05 | Ingestion and perception shall pick up camera/zone changes within 60 s without restart. | S |

### 3.3 Ingestion & recording (F-03)
| ID | Requirement | Pri |
|---|---|---|
| FR-ING-01 | The system shall pull RTSP streams for 4–6 enabled cameras concurrently. | M |
| FR-ING-02 | Each stream shall be recorded as contiguous segments of configurable length (default 10 s) without re-encoding where possible. | M |
| FR-ING-03 | Each segment shall be stored in object storage and announced on Kafka topic `vms.segments.v1` with camera id, segment id, start/end timestamps and URI. | M |
| FR-ING-04 | A keyframe thumbnail shall be stored at least once per second of video. | M |
| FR-ING-05 | On stream failure the ingestor shall reconnect with exponential backoff (max 30 s) and mark gaps. | M |
| FR-ING-06 | A simulator shall replay dataset videos as synchronized RTSP streams. | M |
| FR-ING-07 | Recorded segments shall be retained per a configurable retention policy (default 7 days) and deleted afterwards. | S |

### 3.4 Live monitoring & playback (F-04, F-07)
| ID | Requirement | Pri |
|---|---|---|
| FR-LIVE-01 | Operators shall view live streams in 1, 4 or 6-tile layouts with ≤ 3 s glass-to-glass latency on LAN (WebRTC) or ≤ 8 s (HLS). | M |
| FR-PLAY-01 | Users shall play back any camera for any retained time range. | M |
| FR-PLAY-02 | The playback scrubber shall show per-minute detection density and event markers. | M |
| FR-PLAY-03 | Users shall toggle bounding-box and track-id overlays synchronized with playback (±200 ms). | S |
| FR-PLAY-04 | Users shall download a clip for a selected time range. | C |

### 3.5 Perception & digital twin (F-05, F-06)
| ID | Requirement | Pri |
|---|---|---|
| FR-PER-01 | For each segment the system shall sample frames at a configurable rate (default 2 fps). | M |
| FR-PER-02 | The system shall detect at least: person, bicycle, car, motorcycle, bus, truck, backpack, handbag, suitcase. | M |
| FR-PER-03 | The system shall track objects per camera and keep track ids stable across segment boundaries. | M |
| FR-PER-04 | For each object the system shall record normalized bbox, confidence, dominant upper/lower colour (persons) or colour (others), speed, direction and zones. | M |
| FR-PER-05 | The system shall produce a digital twin JSON per segment conforming to schema `twin.v1` and publish `vms.twin.v1`. | M |
| FR-PER-06 | The system shall compute SigLIP image embeddings for keyframes (≥ 1 per 2 s) and one best crop per track per segment. | M |
| FR-IDX-01 | Twin data shall be persisted: segments and track summaries to PostgreSQL; frame and track embeddings with payload to Qdrant. | M |
| FR-IDX-02 | Indexing shall be idempotent by segment id. | M |

### 3.6 Events, correlation & alerts (F-08, F-10, F-11)
| ID | Requirement | Pri |
|---|---|---|
| FR-EVT-01 | The rule engine shall detect: intrusion (object in restricted zone or zone outside schedule), loitering (dwell > T), crowding (count > N), abandoned object (static bag/suitcase with no owner nearby for > T), running (speed > S). Thresholds configurable per camera/zone. | M |
| FR-EVT-02 | Each candidate shall be verified by a VLM on sampled keyframes, producing verdict, confidence and a one-sentence caption. | M |
| FR-EVT-03 | Rejected candidates shall be stored (for evaluation) but not alerted. | M |
| FR-EVT-04 | Verified events shall be persisted and published on `vms.events.v1`. | M |
| FR-EVT-05 | The VLM gate may be disabled per rule for low-risk event types. | S |
| FR-COR-01 | The correlation service shall link verified events on cameras connected in the topology: overlap edges when time windows intersect within tolerance; transit edges when the later event starts within [min, max] seconds after the earlier ends. | M |
| FR-COR-02 | Linking shall respect an event-type compatibility matrix. | M |
| FR-COR-03 | Correlation groups shall close after no new linked event for `max_transit + grace` seconds and publish `vms.correlations.v1`. | M |
| FR-COR-04 | Unlinked verified events shall form single-event groups. | M |
| FR-ALR-01 | Verified events at or above a configured severity shall be pushed to connected dashboards via WebSocket within the latency in NFR-PERF-03. | M |
| FR-ALR-02 | Operators shall acknowledge and resolve alerts with an optional note; actions shall be audit-logged. | M |
| FR-ALR-03 | Notification channels shall be pluggable; email and Telegram notifiers shall exist but be disabled by default via configuration. | S |

### 3.7 Multimodal search (F-13, F-14, F-15)
| ID | Requirement | Pri |
|---|---|---|
| FR-SRC-01 | Users shall search with a natural-language query plus optional filters (cameras, time range, zones). | M |
| FR-SRC-02 | The system shall decompose the query with an LLM into a validated `QueryPlan` (entities, attributes, actions, temporal and spatial constraints, sub-queries). | M |
| FR-SRC-03 | Coarse retrieval shall combine SigLIP text-to-image vector search, payload filters and dense+sparse text search over event captions, fused by reciprocal rank fusion, returning top-K (default 30) segment-level candidates. | M |
| FR-SRC-04 | Fine retrieval shall have an LLM score each candidate against the plan using twin excerpts and captions, returning score 0–1 and a reasoning trace ≤ 60 words. | M |
| FR-SRC-05 | When a sub-query cannot be answered from the twin, the system shall request JIT refinement (VLM question on keyframes) and cache the answer. | M |
| FR-SRC-06 | Users shall search by uploading an image or cropping a region from a paused frame; results shall be similar tracks across cameras. | M |
| FR-SRC-07 | For top results the system shall return an object-level mask (SAM 2.1-tiny) for the matched object, generated on demand and cached. | S |
| FR-SRC-08 | Each result shall link to playback at the matched timestamp. | M |
| FR-SRC-09 | Every search shall be logged (query, plan, results, latency per stage) for evaluation. | M |
| FR-SRC-10 | Users may choose "fast mode" (coarse only). | S |

### 3.8 Phase-aware event reasoning (F-16)
| ID | Requirement | Pri |
|---|---|---|
| FR-RSN-01 | On correlation-group close (severity ≥ configured) or manual "Analyze", the reasoning service shall gather synchronized clips from all cameras in the group. | M |
| FR-RSN-02 | The TG adapter shall segment the incident into phases {baseline, precursor, escalation, action, aftermath} with start/end timestamps; phases may be empty. | M |
| FR-RSN-03 | For each phase and each camera view, the PhaVR adapter shall produce a caption and answers to the event type's VQA question bank. | M |
| FR-RSN-04 | The system shall assemble an `EvidenceBundle` JSON with evidence ids referencing clip/keyframe URIs. | M |
| FR-RSN-05 | If the fine-tuned adapters are unavailable, the system shall fall back to the base VLM (zero-shot prompts) or the cloud profile, and record which was used. | M |
| FR-RSN-06 | Reasoning jobs shall run one at a time on the GPU and be queued otherwise; queue position shall be visible in the UI. | M |

### 3.9 Incident reports (F-17)
| ID | Requirement | Pri |
|---|---|---|
| FR-INC-01 | The system shall synthesize an `IncidentReport` (schema `incident.v1`) from the evidence bundle via hierarchical LLM synthesis. | M |
| FR-INC-02 | Reports shall be validated against the schema; invalid output shall be retried with the validation error (max 2 retries), then stored as `failed` with raw output. | M |
| FR-INC-03 | Every causal-chain step and contributing factor shall cite ≥ 1 evidence id. | M |
| FR-INC-04 | Users shall view reports with clickable evidence, and export a PDF. | M |
| FR-INC-05 | Reports shall be indexed for semantic search; the UI shall show up to 5 similar past incidents. | S |
| FR-INC-06 | Operators shall edit a report's status (open/reviewed/closed) and add notes; generated text is immutable, notes are separate. | S |

### 3.10 RAG assistant (F-18)
| ID | Requirement | Pri |
|---|---|---|
| FR-AST-01 | Users shall hold multi-turn conversations; sessions and messages persist per user. | M |
| FR-AST-02 | The assistant shall use tools: `search_footage`, `list_events`, `get_incident`, `get_timeline`, `count_objects`, `get_daily_report`. | M |
| FR-AST-03 | Answers shall stream token by token (SSE) and include citations to events, incidents or segments. | M |
| FR-AST-04 | If no supporting evidence is retrieved the assistant shall say so rather than answer from prior knowledge. | M |
| FR-AST-05 | Long conversations shall be summarized to stay within the model context budget. | S |
| FR-AST-06 | `count_objects` shall only run parameterized, pre-defined SQL queries (no free-form SQL generation). | M |

### 3.11 Daily security reports (F-19)
| ID | Requirement | Pri |
|---|---|---|
| FR-RPT-01 | A daily report shall be generated at a configurable time (default 07:00 IST) covering the previous 24 h. | M |
| FR-RPT-02 | Authorized users shall generate a report on demand for any date range ≤ 7 days. | M |
| FR-RPT-03 | Reports shall include: totals by event type/camera/hour, incidents with severity, alert response stats, notable correlations, an LLM narrative summary that cites figures, and charts. | M |
| FR-RPT-04 | Reports shall be exportable as PDF and listed in the UI. | M |

### 3.12 Investigation timeline (F-20)
| ID | Requirement | Pri |
|---|---|---|
| FR-INV-01 | Users shall open a multi-camera timeline showing per-camera lanes with events, correlation links and incidents for a time range. | S |
| FR-INV-02 | Users shall play up to 4 cameras in sync from the timeline. | S |
| FR-INV-03 | Users shall save a case (title, time range, cameras, bookmarked items, notes) and reopen it. | S |

### 3.13 Configuration & LLM providers (F-12)
| ID | Requirement | Pri |
|---|---|---|
| FR-CFG-01 | All LLM/VLM calls shall go through the LLM gateway and select models by task name from a model registry file. | M |
| FR-CFG-02 | Switching `LLM_PROFILE` between `local`, `hybrid`, `cloud` shall require only configuration change and restart. | M |
| FR-CFG-03 | API keys shall be supplied via environment variables/secrets, never committed. | M |

## 4. External interface requirements

### 4.1 User interface
Web dashboard (React) per `style_guide.md §B`. Pages: Login, Live, Playback, Events, Search, Incidents, Investigation, Assistant, Reports, Settings (Cameras, Zones, Topology, Users, Notifications). Keyboard accessible, WCAG 2.1 AA contrast.

### 4.2 Software interfaces
- REST + WebSocket + SSE API under `/api/v1` (OpenAPI generated) — see `design_architecture.md §9`.
- Kafka topics and message schemas — `design_architecture.md §5`.
- LLM providers via LiteLLM: Ollama, Gemini, Groq, OpenRouter.
- S3 API for object storage.

### 4.3 Hardware interfaces
RTSP/H.264 IP cameras or phone camera apps; NVIDIA GPU via CUDA.

### 4.4 Communication interfaces
HTTPS in cloud deployment (TLS via reverse proxy); HTTP on local LAN; RTSP 8554, WebRTC/HLS from media server.

## 5. Data requirements
- **Retention:** video segments 7 days (configurable); twin JSON 30 days; events, incidents, reports, audit log indefinitely.
- **Time:** all timestamps stored in UTC (ISO-8601 / `timestamptz`), displayed in Asia/Kolkata by default.
- **Identifiers:** UUIDv7 for database rows; deterministic string ids for segments (`{camera_id}_{start_utc}_{seq}`) and tracks (`{camera_id}-t{n}`).
- **Schemas:** `twin.v1`, `evidence.v1`, `incident.v1`, `queryplan.v1` versioned in `libs/vms_common/contracts`.

## 6. Non-functional requirements

### 6.1 Performance
| ID | Requirement |
|---|---|
| NFR-PERF-01 | Perception shall sustain 4 cameras × 2 fps (8 fps total) on a 4 GB GPU with backlog not growing over 1 h. |
| NFR-PERF-02 | Ingest → indexed p95 ≤ 30 s (4 cameras). |
| NFR-PERF-03 | Candidate → dashboard alert p95 ≤ 30 s with VLM gate, ≤ 5 s without. |
| NFR-PERF-04 | Search p95 ≤ 1 s (fast mode), ≤ 6 s (hybrid profile), ≤ 20 s (local profile). |
| NFR-PERF-05 | Incident report available ≤ 3 min p95 after group close (single queued job). |
| NFR-PERF-06 | Dashboard pages interactive ≤ 2 s on LAN; API non-GenAI endpoints p95 ≤ 300 ms. |

### 6.2 Reliability
| ID | Requirement |
|---|---|
| NFR-REL-01 | Kafka consumers shall provide at-least-once processing with idempotent writes. |
| NFR-REL-02 | Messages failing 3 times shall go to a dead-letter topic with error details. |
| NFR-REL-03 | Restarting any single service shall lose no segments or events. |
| NFR-REL-04 | The system shall degrade gracefully when GPU/LLM is unavailable: ingestion, recording, playback and rules continue; GenAI features show "queued/unavailable". |

### 6.3 Security
| ID | Requirement |
|---|---|
| NFR-SEC-01 | All user endpoints authenticated and authorized (FR-AUTH-03); tested with a role × endpoint matrix. |
| NFR-SEC-02 | Object storage URLs exposed to browsers shall be presigned with ≤ 15 min expiry. |
| NFR-SEC-03 | CORS restricted to configured origins; security headers set by reverse proxy in cloud. |
| NFR-SEC-04 | Prompt-injection hardening: user text and retrieved text are passed as data in delimited fields; tools are allow-listed and parameterized. |
| NFR-SEC-05 | Audit log for logins, user/camera changes, alert actions, report exports. |
| NFR-SEC-06 | No secrets in the repository (enforced by a pre-commit secret scanner). |

### 6.4 Usability
| ID | Requirement |
|---|---|
| NFR-USE-01 | SUS ≥ 70 with ≥ 8 participants. |
| NFR-USE-02 | Every GenAI output shows its evidence and the model/profile that produced it. |
| NFR-USE-03 | Long-running actions show progress or queue position. |

### 6.5 Maintainability & portability
| ID | Requirement |
|---|---|
| NFR-MNT-01 | Each service is independently buildable and testable; ≥ 60 % line coverage on `libs/` and service domain logic. |
| NFR-MNT-02 | Contracts are versioned; breaking changes require a new topic/schema version. |
| NFR-MNT-03 | CI runs lint, tests and image builds on every PR. |
| NFR-POR-01 | The full stack runs via Docker Compose (dev/cloud) and Kubernetes (minikube) from the same images. |

### 6.6 Observability
| ID | Requirement |
|---|---|
| NFR-OBS-01 | All services emit structured JSON logs with correlation ids (`segment_id`, `event_id`, `group_id`, `request_id`). |
| NFR-OBS-02 | Services expose Prometheus metrics: consumer lag, processing latency histograms, fps, GPU memory, LLM tokens and latency per provider. |

## 7. Evaluation requirements

| ID | What | Method |
|---|---|---|
| EV-01 | Retrieval accuracy | Benchmark ≥ 150 queries (≥ 50 % implicit) with ground-truth segments; R@1/5/10, mAP, temporal IoU; ablation: embeddings only → + filters → + LLM rerank → + JIT |
| EV-02 | Phase reasoning | Held-out annotated clips: phase mIoU; captions BLEU-4, METEOR, ROUGE-L, CIDEr; VQA accuracy; base vs fine-tuned |
| EV-03 | Response quality | ≥ 60 assistant questions + all incident reports from the test set: faithfulness, answer relevance, citation precision (LLM judge from a different model family + 20 % human verification); report rubric 1–5 |
| EV-04 | Latency | Load harness with 2/4/6 cameras; p50/p95 for NFR-PERF-01…05 in local/hybrid/cloud profiles |
| EV-05 | Usability | SUS + task-based study (≥ 8 participants, 4 tasks) |
| EV-06 | Event detection | Precision/recall of rules with and without VLM gate on ShanghaiTech/MEVA labelled segments |

## 8. Traceability (feature → requirements → phase)

| Feature | Requirements | Phase |
|---|---|---|
| F-01 | FR-AUTH-* | 1 |
| F-02, F-09 | FR-CAM-* | 1, 3 |
| F-03 | FR-ING-* | 1 |
| F-04, F-07 | FR-LIVE-01, FR-PLAY-* | 1, 2 |
| F-05, F-06 | FR-PER-*, FR-IDX-* | 2 |
| F-08 | FR-EVT-* | 3 |
| F-10 | FR-COR-* | 3 |
| F-11 | FR-ALR-* | 3 |
| F-12 | FR-CFG-* | 3 |
| F-13–F-15 | FR-SRC-* | 4 |
| F-16 | FR-RSN-* | 5 |
| F-17 | FR-INC-* | 6 |
| F-18 | FR-AST-* | 6 |
| F-19 | FR-RPT-* | 6 |
| F-20 | FR-INV-* | 6 |
| F-21–F-23 | NFR-POR-01, NFR-OBS-* | 7 |
| F-24 | EV-01…06 | 4, 5, 7 |
