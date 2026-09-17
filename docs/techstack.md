# Tech Stack

| | |
|---|---|
| **Version** | 0.1 — 17 Sep 2026 |
| **Rule** | Pin exact versions in `uv.lock` / `package-lock.json` / image tags during P1. The "verify" column marks things whose names, tags, quotas or licences change often — check them on setup day, then update this file. |

---

## 1. Summary

| Layer | Choice |
|---|---|
| Language (backend/ML) | Python 3.11 |
| Backend framework | FastAPI + Uvicorn, Pydantic v2 |
| Streaming | Apache Kafka (KRaft) + aiokafka |
| Media server | MediaMTX (RTSP in → WebRTC/HLS out) |
| Video I/O | FFmpeg, PyAV, OpenCV |
| Detection / tracking | Ultralytics YOLO11 + ByteTrack (`supervision`) |
| Embeddings | SigLIP 2 base (image/text), bge-small-en-v1.5 + BM25 (FastEmbed) |
| Segmentation (grounding) | SAM 2.1 hiera-tiny |
| VLM / LLM (local) | Ollama: Qwen2.5-VL-3B, Qwen2.5-3B; transformers + PEFT for fine-tuned adapters |
| VLM / LLM (cloud, free tiers) | Gemini Flash, Groq (Llama 3.3 70B), OpenRouter free models |
| LLM abstraction | LiteLLM |
| Fine-tuning | Unsloth + TRL + PEFT (QLoRA) on Kaggle / Colab free GPUs |
| Annotation | Label Studio |
| Vector DB | Qdrant |
| Relational DB | PostgreSQL 16 + SQLAlchemy 2 (async) + Alembic |
| Cache / locks / pub-sub | Redis 7 (or Valkey) |
| Object storage | S3-compatible (MinIO; SeaweedFS fallback) via boto3 |
| PDFs | Jinja2 + WeasyPrint, matplotlib charts |
| Frontend | React 18 + Vite + **JavaScript (JSX)** + Tailwind CSS + shadcn/ui |
| Frontend libs | React Router, TanStack Query, Zustand, react-hook-form + zod, hls.js, Recharts, lucide-react |
| Auth | JWT (PyJWT), Argon2id (pwdlib) |
| Packaging | uv (workspace), npm |
| Quality | Ruff, pytest, pytest-asyncio, testcontainers, ESLint, Prettier, Vitest, pre-commit, gitleaks |
| Containers | Docker, Docker Compose |
| Orchestration | Kubernetes (minikube) + Kustomize + Helm (for Strimzi, CloudNativePG, Qdrant, kube-prometheus-stack) |
| CI/CD | GitHub Actions → GHCR (multi-arch images) |
| Observability | Prometheus, Grafana, structlog |
| Experiment tracking | Weights & Biases (free) or MLflow (local) |

## 2. Backend

| Component | Choice | Why | Alternatives considered | Verify |
|---|---|---|---|---|
| Framework | **FastAPI** | Async I/O for LLM calls, Kafka, WS/SSE; Pydantic models double as report schemas; OpenAPI enables contract-first frontend work | Django + DRF (batteries-included admin/ORM we don't need; async story weaker), Flask | — |
| Server | Uvicorn (dev), Gunicorn + Uvicorn workers (prod) | Standard | Hypercorn | — |
| Settings | pydantic-settings | Typed env config shared via `vms_common.config` | dynaconf | — |
| ORM / migrations | SQLAlchemy 2.0 async + asyncpg + Alembic | Mature, async, one migration history | SQLModel (thin wrapper; fine but less flexible), Tortoise | — |
| Kafka client | **aiokafka** | Pure-Python asyncio, fits FastAPI services; messages are small | confluent-kafka (faster, librdkafka; use if throughput becomes an issue) | — |
| HTTP client | httpx | Async, used by BFF proxy and gateway | aiohttp | — |
| Scheduling | Kubernetes CronJob / supercronic (Compose) | Scheduler outside app process; learning k8s | APScheduler | — |
| PDF | WeasyPrint + Jinja2 | HTML/CSS → PDF, matches dashboard styling | ReportLab (verbose), Playwright print (heavy) | system libs in Dockerfile |
| Logging | structlog (JSON) | Correlation ids, machine-parsable | loguru | — |
| Metrics | prometheus-client / prometheus-fastapi-instrumentator | Standard | OpenTelemetry (optional later) | — |

## 3. Streaming & media

| Component | Choice | Why | Notes / verify |
|---|---|---|---|
| Message bus | **Apache Kafka, KRaft mode** (official `apache/kafka` image) | Decouples ingestion from GPU; replay; partitions per camera; industry-recognised on a résumé | Avoid Bitnami images (catalogue changed in 2025) — verify |
| Kafka UI | kafbat/kafka-ui | Inspect topics, DLQ | — |
| Media server | **MediaMTX** | RTSP server + WebRTC (≈ sub-second) + HLS for browsers; trivial config | — |
| Recording | FFmpeg segment muxer (`-c copy`, MPEG-TS 10 s) | No re-encode, cheap CPU | fMP4 alternative |
| Decoding | PyAV (+ OpenCV for image ops) | Frame-accurate timestamps | Decord for training data loaders |
| Camera simulation | FFmpeg `-re -stream_loop -1` → MediaMTX | Replays datasets as live RTSP | Phone apps that publish RTSP work for real live demos |

## 4. Computer vision & embeddings

| Task | Choice | VRAM (est.) | Why | Verify |
|---|---|---|---|---|
| Detection | **YOLO11s** (n for CPU/cloud) FP16 | ~0.3–0.5 GB | Fast, COCO classes cover people/vehicles/bags | AGPL-3.0 licence |
| Tracking | ByteTrack via `supervision` | CPU | Per-camera instances with persistable state | — |
| Colour attributes | HSV k-means on crops (OpenCV) | CPU | Cheap, explainable | Optional PAR model later |
| Image/text embedding | **SigLIP 2 base (patch16, 224)**, fallback SigLIP base | ~0.5 GB GPU; CPU for query side | Strong zero-shot text↔image retrieval; same space for text and image queries | HF model id |
| Text embedding | bge-small-en-v1.5 via **FastEmbed** (ONNX, CPU) | CPU | Small, good quality, Qdrant-native | — |
| Sparse | BM25 via FastEmbed (`Qdrant/bm25`) | CPU | Hybrid search on captions | — |
| Grounding masks | **SAM 2.1 hiera-tiny**, box prompts | ~0.4 GB | Object-level grounding (Shen et al.) at low cost | checkpoint name |

## 5. GenAI models

### 5.1 Local (Ollama / transformers)
| Task | Model | Quantization | Est. VRAM | Verify |
|---|---|---|---|---|
| Event verification, JIT VQA | Qwen2.5-VL-3B-Instruct (`qwen2.5vl:3b`) | Q4_K_M | ~3.2–3.6 GB with ≤ 4 small images | Ollama tag; consider newer small Qwen-VL releases if they fit better |
| Query decomposition, rerank, synthesis, assistant | Qwen2.5-3B-Instruct (`qwen2.5:3b`) | Q4_K_M | ~2.2 GB | Tool-calling support in Ollama |
| Phase grounding (TG) & phase captioning/VQA (PhaVR) | Qwen2.5-VL-3B-Instruct + 2 LoRA adapters | bitsandbytes NF4 | ~2.8–3.4 GB | transformers/PEFT versions matching training |

Local 3B text models are adequate for development and schema-constrained tasks, but weak at long-context reranking and multi-step tool use; the `hybrid` profile exists for demo quality. Evaluation reports both profiles.

### 5.2 Cloud (free tiers only)
| Provider | Use | Why | Verify |
|---|---|---|---|
| Google Gemini API (Flash) | Hybrid/cloud reasoning; cloud vision | Multimodal, generous free tier | Current free models + rate limits; data-use terms of free tier |
| Groq | Fast text fallback; evaluation judge (Llama 3.3 70B) | Very low latency; different model family from generator | Model ids + limits |
| OpenRouter (`:free` models) | Extra fallback | Many free models | Availability changes frequently |

**Do not** train on outputs from proprietary APIs without checking their terms. Pseudo-labels for training come from open models.

### 5.3 Fine-tuning environment
| Item | Choice | Notes / verify |
|---|---|---|
| GPUs | Kaggle Notebooks (T4 ×2 / P100), Google Colab free T4 | Kaggle ≈ 30 GPU-h/week per account — verify; both builders have accounts → parallel runs |
| Framework | **Unsloth** (QLoRA, memory-efficient VLM fine-tuning) + TRL `SFTTrainer` + PEFT | Fallback: LLaMA-Factory |
| Tracking | Weights & Biases free / MLflow | Log configs, metrics, adapter artefacts |
| Artefacts | Adapters pushed to a private Hugging Face repo or Kaggle dataset → synced to `vms-models` bucket | Keep base model id + commit hash in `adapter_config.json` |
| Data format | Frames pre-extracted (JPEG, ≤ 360 p) + JSONL instructions uploaded as a Kaggle dataset | Avoids video decoding in notebooks |

## 6. Datasets

| Dataset | Views | Role in project | Verify |
|---|---|---|---|
| **MEVA** (Multiview Extended Video with Activities) | Many synchronized indoor/outdoor cameras | Multi-camera correlation, multi-view phase reasoning, activity-style search queries | Registration/licence; very large — download a scoped subset (P1-D6) |
| **WILDTRACK** | 7 synchronized, overlapping HD cameras | Overlap-edge correlation demo, live multi-camera simulation | Licence |
| **UCF-Crime** | Single view, 13 anomaly classes (untrimmed) | Phase annotation for TG/PhaVR fine-tuning; incident search queries | Research use |
| **ShanghaiTech Campus** | Single view per scene, campus anomalies | Rule/event precision-recall (running, loitering-like, bikes) | Research use |
| Own recordings (team members, consented) | Phone cameras | Live demo, after-hours scenarios | Consent of people filmed |

Deferred: CUHK Avenue, DCSASS, WTS (MP-PVIR's traffic dataset — a possible reproduction baseline in future work).

## 7. Data stores

| Store | Choice | Why | Alternatives |
|---|---|---|---|
| Vectors | **Qdrant** | Payload-indexed filtering, named dense + sparse vectors, good Python client, Helm chart | pgvector (simpler, weaker hybrid/filtering at scale), FAISS (library, no server/filters) |
| Relational | **PostgreSQL 16** | JSONB for reports, `timestamptz`, `SKIP LOCKED` queues | — |
| Cache/locks | **Redis 7** (or Valkey 8) | GPU lease, LLM response cache, WS fan-out across API replicas, tracker checkpoints | — |
| Objects | **S3-compatible**: MinIO (default) / SeaweedFS | Same API locally and in cloud | Verify MinIO community image distribution & console status before pinning |

## 8. Frontend (JavaScript only)

| Concern | Choice | Notes |
|---|---|---|
| Build | **Vite** (`react` template, not `react-ts`) | Fast HMR |
| UI kit | **shadcn/ui** with `"tsx": false` in `components.json` | Components generated as `.jsx` |
| Styling | Tailwind CSS with CSS-variable tokens (see `style_guide.md §B`) | Tailwind v4 is fine if shadcn CLI setup matches — verify at scaffold |
| Routing | React Router | |
| Server state | TanStack Query | Caching, polling camera status |
| Client state | Zustand | Player sync, layout, alert tray |
| Forms & validation | react-hook-form + **zod** | zod replaces the safety TypeScript would give at API boundaries |
| Video | hls.js (HLS), native WebRTC via MediaMTX WHEP | Live + playback |
| Charts | Recharts | Density scrubber, report charts |
| Timeline | Custom SVG/canvas component (+ `@dnd-kit` not needed) | Signature component — see style guide |
| Icons | lucide-react | |
| Streaming chat | `fetch` + ReadableStream SSE parser (`eventsource-parser`) | POST-based SSE |
| Tests | Vitest + React Testing Library; Playwright for 3–5 smoke flows | |
| Types-lite | JSDoc `@typedef` for API shapes, `// @ts-check` optional | No TypeScript compilation |

## 9. DevOps

| Concern | Choice | Notes |
|---|---|---|
| Dev OS | Windows 11 + **WSL2 Ubuntu** (or native Linux) | Run Docker, GPU, minikube inside WSL2 |
| GPU in containers | NVIDIA Container Toolkit | Verify `nvidia-smi` inside a container first (P1) |
| Local stack | Docker Compose profiles | `make up PROFILE=infra,core` |
| Kubernetes | **minikube** (docker driver, `--gpus all`) | GPU fallback: `ExternalName` to host services (design §12.2) |
| Operators/charts | Strimzi (Kafka), CloudNativePG (Postgres), Qdrant Helm, kube-prometheus-stack, ingress-nginx, NVIDIA device plugin | |
| Manifests | Kustomize (base + overlays) | Learn raw manifests first, Helm only for third-party |
| CI | GitHub Actions: lint, test, build per changed path | Path filters keep CI fast |
| Registry | GHCR, multi-arch via `docker buildx` | ARM free-tier VMs |
| Cloud VM | Free-tier / student-credit VM (e.g. Oracle Cloud Always Free Ampere, Azure for Students, GitHub Student Pack credits) | Verify eligibility & limits |
| Reverse proxy | Caddy (auto TLS) | |
| Secrets | `.env` (git-ignored) → k8s `Secret` via Kustomize generator | gitleaks in pre-commit |

## 10. Hardware assumptions

| Item | Assumed | Impact if lower |
|---|---|---|
| GPU | NVIDIA, 4 GB VRAM ×2 laptops | — (plan already built for this) |
| RAM | 16 GB | 8 GB → `lite` profile (2 cams), no Label Studio/Grafana simultaneously |
| Disk | ≥ 150 GB free | Scope dataset subsets; shorten retention |
| Network | LAN between laptops for two-node demo | Single-laptop + `hybrid` profile |

## 11. Ports (dev)

| Service | Port |
|---|---|
| api | 8000 |
| retrieval | 8010 |
| reasoning | 8020 |
| perception (internal grounding) | 8030 |
| frontend (Vite) | 5173 |
| MediaMTX RTSP / HLS / WebRTC | 8554 / 8888 / 8889 |
| Kafka | 9092 |
| kafka-ui | 8080 |
| Postgres | 5432 |
| Qdrant | 6333 (HTTP), 6334 (gRPC) |
| Redis | 6379 |
| Object storage API / console | 9000 / 9001 |
| Ollama | 11434 |
| Label Studio | 8081 |
| Prometheus / Grafana | 9090 / 3000 |
