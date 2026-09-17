# Project Context

> **Read this first.** This file is the single source of background for humans and AI agents (Claude Code) working on the repo. It explains *why* the project exists, *what* the research foundation is, and *which decisions are already locked*.

| | |
|---|---|
| **Project** | GenAI-Powered Video Management System with Multimodal Search, Event Reasoning and Automated Incident Summarization |
| **Codename** | `genai-vms` |
| **Doc version** | 0.1 (kickoff) — 17 Sep 2026 |
| **Status** | Phase I (literature + proposal) complete → implementation starting |

---

## 1. What we are building (one paragraph)

An intelligent video management system (VMS) that ingests **live multi-camera CCTV streams**, converts every clip into a **structured "digital twin"** (objects, people, attributes, tracks, zones, embeddings), detects and **correlates events across cameras**, lets operators **search footage in natural language or by image**, runs **phase-aware causal reasoning** on incidents, and automatically writes **incident reports, daily security reports and grounded answers** to operator questions. Evaluation focuses on retrieval accuracy, response quality, latency and usability.

## 2. Academic context

| Item | Detail |
|---|---|
| Program | CCVR (Computer Vision Research Center) COE Internship, RV College of Engineering, Bengaluru |
| Department | Master of Computer Applications |
| Guide | Prof. Chandrani Chakravorty, Assistant Professor, Dept. of MCA |
| Phase I evaluation | 15–18 Sep 2026 (literature survey + proposal deck) |
| Phase II review | ≈ 2 weeks after kickoff (≈ early Oct 2026) — **exact date TBC** |
| Later reviews | Not yet announced — plan assumes ~2-week phases |

### Team and roles

| Member | USN | Role in this repo |
|---|---|---|
| Divyansh Pankaj Mishra | 1RV25MC028 | **Builder — Track D** (see `team/DIVYANSH.md`) |
| Jatin Bansal | 1RV25MC044 | **Builder — Track J** (see `team/JATIN.md`) |
| Kuldeep Nagar | — | Documentation, testing, evaluation (no implementation) |
| Pankaj Raikar | — | Documentation, testing, evaluation (no implementation) |

Implementation is split **~50/50 between Divyansh and Jatin** (161 story points each). Kuldeep and Pankaj run the *support track*: test-case writing, evaluation ground-truth creation, phase-annotation labeling (proposed — confirm with them), usability study, and report/slide documentation.

## 3. Official problem statement

> This project aims to develop an advanced Intelligent Video Management System that combines computer vision, multimodal AI, semantic search and Retrieval-Augmented Generation. Surveillance videos will be analysed to identify objects, persons, activities, locations and important events. The resulting metadata and visual representations will be indexed in databases and vector stores. Users will be able to search the surveillance archive using natural-language queries and retrieve relevant events and video segments. A GenAI model will reason over the retrieved information and generate incident summaries, daily security reports and answers to user questions. The system will also support multi-camera event correlation and timeline-based investigation. Evaluation will focus on retrieval accuracy, response quality, latency and system usability.

## 4. Research foundation

Numbering follows the analysis sections of the Literature Survey.

| # | Paper | Pillar | What we **adopt** | What we **adapt** | What we **drop / defer** |
|---|---|---|---|---|---|
| 1 | De Silva et al., *LLMs for Video Surveillance Applications*, IEEE TENCON 2024 (arXiv:2501.02850) | Summarization | Video → text is a searchable, compact archive; cross-camera summaries | Captions are generated **only for events / on demand**, not every frame (cost) | Cloud-only VLM pipeline (we are local-first) |
| 2 | Zhen et al., *MP-PVIR*, arXiv:2511.14120 | Event reasoning + incident reports | Phase segmentation → phase-specific multi-view captioning/VQA → LLM synthesis → JSON report with schema validation + retry | Traffic phases → **general-surveillance phase taxonomy**; Qwen2.5-VL-7B → **3B QLoRA** (free cloud GPUs, 4 GB local VRAM); **two LoRA adapters on one base** | Gaze/pose modalities (future) |
| 3 | Shen et al., *Reasoning Text-to-Video Retrieval via Digital Twins*, arXiv:2511.12371 | Multimodal search | Structured per-frame digital twin; LLM query decomposition; coarse embedding filter → fine LLM reasoning; just-in-time refinement; object-level grounding | **Lightweight twin** (detector + tracker + attributes + SigLIP embeddings); masks generated **on demand** with SAM 2.1-tiny | Depth estimation, full per-frame segmentation (too heavy for live CCTV on 4 GB) |

**Unifying idea (our contribution):** one structured video representation (the digital twin) feeds *all three pillars*, running on continuous live streams rather than short benchmark clips, with a single operator-facing explanation per incident.

## 5. Decision log (kickoff, 17 Sep 2026)

| ID | Decision | Rationale |
|---|---|---|
| D-01 | Backend = **FastAPI** (not Django) | Async I/O for inference calls, Kafka, SSE/WebSockets; Pydantic doubles as schema validation for reports; auto OpenAPI for contract-first parallel work |
| D-02 | **Kafka** carries *metadata messages*, never raw frames | Video segments go to S3-compatible object storage; Kafka messages carry URIs. Decouples ingestion from slow GPU inference, enables replay |
| D-03 | Event reasoning = **full MP-PVIR approach (fine-tuning)** | Chosen by team; phase-annotate a surveillance subset, QLoRA fine-tune on free cloud GPUs |
| D-04 | Search = **lightweight digital twin** (option B) | Full SAM-2 + depth per frame is infeasible for live streams on 4 GB VRAM |
| D-05 | **Live streams required**, plus replayed datasets | Resume/demo value; datasets are replayed as RTSP to simulate cameras |
| D-06 | Scale target **4–6 cameras** | Fits 4 GB perception budget at 2–5 sampled fps per camera |
| D-07 | Both builders have **4 GB VRAM**; training on **free cloud GPUs** (Kaggle/Colab) | Dictates 3B-class models, 4-bit quantization, one-model-at-a-time GPU lease |
| D-08 | LLMs: **local-first (Ollama)** with **config switch** to cloud APIs; **free tiers only** | `LLM_PROFILE=local|hybrid|cloud` via LiteLLM |
| D-09 | Multi-camera correlation is **mandatory** → MEVA + WILDTRACK added | UCF-Crime/ShanghaiTech are single-view |
| D-10 | Correlation v1 = **time-aligned linking** using camera topology only | Appearance re-ID deferred to future work |
| D-11 | Search input: **text + image** | |
| D-12 | Assistant: **multi-turn** RAG with tool use | |
| D-13 | Daily reports: **scheduled + on demand**, with **PDF export** | |
| D-14 | Alerts: **dashboard only**; email/Telegram as disabled plugins | |
| D-15 | Auth: **simple RBAC + JWT** (admin / operator / viewer) | |
| D-16 | **No face blurring** | Out of scope by team decision |
| D-17 | Frontend: **React + Vite + Tailwind + shadcn/ui in JavaScript (JSX)** — **no TypeScript** | Team skill set |
| D-18 | Vector store: **Qdrant**; metadata: **PostgreSQL** | Payload filtering + dense/sparse hybrid search |
| D-19 | Deployment: **Docker Compose for cloud VM**, **Kubernetes (minikube) for local demo** | Team wants to learn Kubernetes |
| D-20 | **Monorepo**, modular services + shared libs (uv workspace) | Most modular while keeping contracts in one place |
| D-21 | Work split: **independent parallel tracks per phase**, contract-first | Equal skills; vertical slice ownership (backend + its UI) |
| D-22 | Backlog: **epics → stories with points + acceptance criteria** | |
| D-23 | Both builders use **Claude Code** → `CLAUDE.md` at root | |
| D-24 | Style guide covers **code and UI** | |

Architecture decision records (ADRs) for technical choices live in `design_architecture.md §14`.

## 6. Constraints

- **Compute:** 2 laptops × 4 GB VRAM (HP Victus-class, likely Windows → use WSL2). No paid GPUs. Fine-tuning on Kaggle/Colab free tiers only.
- **Money:** ₹0 budget. Free API tiers (Gemini, Groq, OpenRouter free models) with rate limits → cache aggressively.
- **People:** 2 builders, college schedule; ~2-week phases.
- **Time:** Phase II review ≈ end of Phase 1. Total plan = 7 phases ≈ 14 weeks.
- **Data:** Public research datasets only (check each licence; research / non-commercial use). No personal footage of non-consenting people beyond team members in demo recordings.
- **Licences to be aware of:** Ultralytics YOLO is AGPL-3.0 (fine for an open academic repo; not for closed commercial use).

## 7. Scope

**In scope:** everything in the problem statement plus live streams, K8s local deployment, cloud Docker deployment, evaluation suite.

**Out of scope / future work:** cross-camera person re-identification, face recognition, face blurring, gaze/pose modalities, depth-aware digital twins, audio analytics, email/Telegram delivery (plugins exist but are disabled), mobile app, multi-tenant SaaS.

## 8. Glossary

| Term | Meaning |
|---|---|
| **Segment** | A fixed-length (default 10 s) recorded chunk of one camera's stream stored in object storage |
| **Digital twin** | Structured JSON for a segment: sampled frames → objects (track id, category, bbox, attributes, zones, motion) + track summaries |
| **Track** | One object followed over time within a camera (ByteTrack id), e.g. `cam03-t412` |
| **Zone** | Polygon on a camera view (e.g. entrance, restricted area) with optional schedule |
| **Topology** | Graph of cameras: *overlap* edges (same area, different view) and *transit* edges (A→B within min/max seconds) |
| **Event candidate** | Rule-engine hit (loitering, intrusion, …) before verification |
| **Verified event** | Candidate confirmed by the VLM gate |
| **Correlation group** | Set of verified events on different cameras linked in time via topology |
| **Phase** | One of 5 temporal stages of an incident: baseline, precursor, escalation, action, aftermath |
| **TG adapter** | LoRA adapter for temporal phase grounding (MP-PVIR's TG-VLM analogue) |
| **PhaVR adapter** | LoRA adapter for phase-specific multi-view captioning + VQA |
| **Evidence bundle** | JSON of phase timeline + per-phase/per-view captions + VQA answers + evidence URIs |
| **Incident report** | Final structured JSON (and PDF) produced by LLM synthesis over an evidence bundle |
| **JIT refinement** | Just-in-time call to a VLM/SAM when the twin lacks information needed to answer a query |
| **GPU lease** | Redis lock ensuring only one heavy model occupies a 4 GB GPU at a time |
| **LLM profile** | `local` (Ollama), `hybrid` (local perception + cloud reasoning), `cloud` |

## 9. Open questions

1. Exact Phase II date and the dates of later reviews (the kickoff answer was cut off: *"phase 2 will be in 2 weeks approx and we …"*).
2. Confirm Kuldeep and Pankaj will do phase-annotation labeling (needed from week 6 to week 9).
3. Guide's approval of the general-surveillance phase taxonomy (`design_architecture.md §8.2`).
4. Laptop RAM (plan assumes 16 GB; 8 GB needs the `lite` compose profile).
5. MEVA access/download size — scope the subset early (Phase 1, story P1-D6).

## 10. Document map

| File | Purpose |
|---|---|
| `README.md` | Repo front page, quick start |
| `CLAUDE.md` | Instructions for Claude Code agents |
| `docs/context.md` | This file |
| `docs/PRD.md` | Product requirements — what and why |
| `docs/SRS.md` | Software requirements — testable FR/NFR |
| `docs/design_architecture.md` | System design, contracts, schemas, ADRs |
| `docs/techstack.md` | Every technology choice with rationale |
| `docs/style_guide.md` | Code, Git, API and UI conventions |
| `docs/backlog.md` | Epics → stories → points → acceptance criteria |
| `docs/team/DIVYANSH.md` | Track D workload |
| `docs/team/JATIN.md` | Track J workload |
