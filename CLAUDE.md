# CLAUDE.md

Guidance for Claude Code working in this repository. Keep this file short; details live in `docs/`.

## Project in one paragraph

GenAI-VMS ingests live multi-camera CCTV (RTSP → MediaMTX), records 10 s segments to S3-compatible storage, announces them on Kafka, builds a per-segment **digital twin** (YOLO11 + ByteTrack + attributes + SigLIP 2 embeddings), indexes it in PostgreSQL + Qdrant, detects rule-based events verified by a VLM, correlates events across cameras by topology and time, and uses GenAI for reasoning-based search, phase-aware incident reasoning (fine-tuned Qwen2.5-VL-3B LoRA adapters), incident reports, daily reports and a multi-turn RAG assistant. Backend: Python 3.11 + FastAPI. Frontend: React + Vite + Tailwind + shadcn/ui in **JavaScript**.

## Read before non-trivial work

1. `docs/context.md` — decisions already made (do not re-litigate them in code).
2. `docs/design_architecture.md` — services, topics, schemas, contracts (§5–§10, §16).
3. `docs/backlog.md` — find the story id you are working on and its acceptance criteria.
4. `docs/style_guide.md` — code conventions (Part A) and UI rules (Part B).

## Repo map

```text
libs/vms_common/   contracts (Pydantic), fixtures, kafka, storage, llm gateway, config, logging
libs/vms_db/       SQLAlchemy models + single Alembic history (schemas: core, media, vision, events, reasoning, retrieval)
services/          ingestion · perception(+grounding) · indexer · events · correlation · retrieval · reasoning · api
frontend/          React SPA (JSX) — src/features/<feature>/{api.js,schemas.js,components,pages}
ml/                annotation · datasets · training (Kaggle/Colab notebooks) · evaluation
config/            models.yaml · rules.yaml · correlation.yaml · vqa_bank.yaml
tools/             camera_sim · seed
deploy/            compose (profiles) · k8s (kustomize base + overlays)
```

## Commands

```bash
make setup                          # uv sync --all-packages, npm ci, pre-commit install
make up PROFILE=infra,core          # docker compose profiles: infra, core, perception, genai, tools, obs, lite
make down
make test                           # all python tests (unit); make test-int for testcontainers
make test SVC=perception            # one service
make lint                           # ruff check + ruff format --check + eslint
make migrate                        # alembic upgrade head
make migration MSG="add zones"      # alembic revision --autogenerate
make topics                         # create Kafka topics
make sim                            # start camera simulator
cd frontend && npm run dev          # Vite on :5173
make k8s-up / make k8s-down         # minikube deployment
```

Python packages are managed with **uv** only (`uv add --package <svc> <dep>`). Never use pip directly.

## Hard rules

- **No TypeScript.** Frontend files are `.jsx`/`.js`. shadcn components are generated with `tsx: false`. Validate API data with **zod** in `features/*/api.js`; document shapes with JSDoc.
- **Contracts are change-controlled.** Anything crossing a service boundary is a Pydantic model in `libs/vms_common/contracts/` with a `schema_version` and a fixture in `libs/vms_common/fixtures/`. Adding an optional field is fine; removing/renaming/retyping requires a new `v<n>` and topic. Never define a cross-service payload inside a service.
- **Services never import other services.** Only `libs/*`. `domain/` code never imports `adapters/`.
- **No video bytes on Kafka.** Messages carry `s3://` URIs; stay under 1 MB.
- **All LLM/VLM calls go through `vms_common.llm.LLMGateway`** with a task name from `config/models.yaml`. Never call Ollama, Gemini, Groq or OpenRouter SDKs directly. Structured outputs use `response_model=` (validated + retried).
- **Prompts live in files:** `libs/vms_common/llm/prompts/<task>/<version>.md`. Changing wording = new version.
- **GPU is 4 GB.** Heavy GenAI models run only under the GPU lease. Don't load a second model in a process "just in case". Perception (YOLO + SigLIP + SAM-tiny) shares one process. Cap frames/pixels for VLM calls.
- **Kafka consumers:** validate → idempotent write → commit. Use the base consumer in `vms_common.kafka`; don't hand-roll offset commits.
- **Time:** timezone-aware UTC everywhere; IST only in UI/PDF formatting.
- **Config:** read settings through `pydantic-settings` classes; no `os.environ` in business code. Secrets only via env; never commit `.env`, keys or tokens.
- **No generated SQL.** The assistant's `count_objects` tool uses pre-defined parameterized queries only.
- **Every GenAI claim cites evidence ids** (incident reports, assistant answers, daily narratives).
- **Tests:** every story adds unit tests for domain logic. Tests never hit the network or real LLMs — use `FakeGateway` and fixtures. Integration tests use testcontainers.

## Ownership (two builders working in parallel)

Track D = Divyansh, Track J = Jatin. See `docs/design_architecture.md §3` and `CODEOWNERS`.
- Stay inside the paths owned by the story's track. If a change is needed in the other track's code, **stop and describe it** (or open a separate small PR tagged `contract` / `cross-track`) instead of editing it silently.
- When the other track's piece isn't built yet, build against the fixture — don't stub their service inside yours.

## Workflow for a story

1. Find `P<phase>-<D|J><n>` in `docs/backlog.md`; restate the acceptance criteria as a checklist.
2. Branch `d/P2-D2-bytetrack-state` or `j/P3-J2-correlation-core`.
3. Contracts/fixtures first if the story touches a boundary.
4. Implement in small commits (Conventional Commits, scope = service): `feat(correlation): union-find grouping`.
5. Run `make lint` and `make test SVC=<service>`; for UI, `npm run lint && npm test`.
6. Update the service `README.md` and any doc whose behaviour changed; tick the story's checkboxes in `docs/backlog.md`.

## How-tos

**New Kafka message/contract** → model in `contracts/<name>.py` → fixture JSON → round-trip test → topic in `design_architecture.md §5.2` and `make topics` config → producer/consumer using `vms_common.kafka`.

**New API endpoint (services/api)** → router in `api/`, request/response schemas, `require_role(...)`, error envelope codes, add to role × endpoint test matrix, add to `design_architecture.md §9` if new area.

**New event rule** → `services/events/src/events/domain/rules/<rule>.py` with `@rule("<id>")` and param schema → defaults in `config/rules.yaml` → positive/negative unit tests with synthetic twin sequences.

**New GenAI task** → add task to every profile in `config/models.yaml` → prompt file → Pydantic output model → call via gateway → recorded responses for `FakeGateway` tests.

**New frontend feature** → `src/features/<name>/` with `api.js` (TanStack Query + zod), `pages/`, `components/`; route in `src/app/router.jsx`; tokens only (no raw hex, no arbitrary Tailwind colours); sentence-case copy per style guide §B.8.

**DB change** → edit models in `libs/vms_db` under the right schema → `make migration MSG=…` → review the autogenerated file by hand → never edit an already-merged migration.

## Environment notes

- Dev machines: Windows + **WSL2 Ubuntu**, Docker with NVIDIA Container Toolkit, 4 GB VRAM. Run everything inside WSL2, not PowerShell.
- `VMS_LLM_PROFILE=local|hybrid|cloud`. Default for development is `local`; demos use `hybrid`.
- Two-laptop demo: laptop A runs perception; laptop B runs Ollama/reasoning/events/retrieval. Hosts are set via env, never hard-coded.
- Model names and free-tier limits change — if a model tag fails, check `docs/techstack.md` "verify" notes and update `config/models.yaml`, not code.

## Don'ts

- Don't add TypeScript, Redux, Next.js, Django, Celery or new infrastructure services without an ADR in `design_architecture.md §14`.
- Don't add face recognition, face blurring or re-identification (out of scope; see `docs/context.md §7`).
- Don't store presigned URLs in the database; generate them per request (≤ 15 min).
- Don't catch-and-ignore exceptions in consumers; let the base class retry and dead-letter.
- Don't rewrite large files wholesale for small changes; keep diffs reviewable.
