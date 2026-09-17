# Product Requirements Document (PRD)

| | |
|---|---|
| **Product** | GenAI-VMS — GenAI-Powered Video Management System |
| **Version** | 0.1 (kickoff draft) |
| **Date** | 17 Sep 2026 |
| **Authors** | Divyansh Pankaj Mishra, Jatin Bansal |
| **Reviewers** | Kuldeep Nagar, Pankaj Raikar, Prof. Chandrani Chakravorty |
| **Related** | `context.md`, `SRS.md`, `design_architecture.md`, `backlog.md` |

---

## 1. Overview

Security teams record far more footage than anyone can watch. Today's "smart" VMS products detect objects and raise anomaly flags, but an operator still cannot *ask* the archive a question, cannot see *why* an incident unfolded, and still writes every incident report by hand.

GenAI-VMS turns live CCTV into a searchable, explainable record. Every clip becomes a structured digital twin; events are detected, verified and linked across cameras; operators search with plain language or an image; and a GenAI layer reasons over the evidence to produce incident reports, daily security reports and grounded answers.

## 2. Problem

| Pain | Today | Consequence |
|---|---|---|
| Finding footage | Scrub timelines camera by camera; keyword tags at best | Hours per investigation; implicit questions ("anyone acting suspicious near the gate after hours?") are unanswerable |
| Understanding incidents | Binary anomaly flag or confidence score | No causal explanation; operators must reconstruct what happened |
| Multi-camera events | Each camera reviewed in isolation | Events that move across cameras are missed or misread |
| Reporting | Manual incident write-ups and shift summaries | Slow, inconsistent, often skipped |
| Cost of GenAI | Cloud VLM APIs per frame | Not viable for continuous streams |

## 3. Goals and non-goals

### Goals
- **G1 — Search:** Retrieve the right event or video segment from a multi-camera archive with natural-language or image queries, including implicit queries, with object-level grounding.
- **G2 — Reasoning:** Explain incidents phase by phase across camera views, grounded in visual evidence.
- **G3 — Summarization:** Auto-generate structured incident reports, daily security reports and conversational answers that cite evidence.
- **G4 — Correlation:** Link events across cameras into a single investigation timeline.
- **G5 — Practicality:** Run 4–6 live cameras on a 4 GB-VRAM laptop setup, local-first, with zero paid services.
- **G6 — Rigor:** Publishable evaluation of retrieval accuracy, response quality, latency and usability.

### Non-goals (v1)
- Face recognition, face blurring, cross-camera person re-identification.
- Replacing certified commercial VMS features (PTZ control, ONVIF device management, NVR hardware).
- Multi-tenant SaaS, billing, mobile apps.
- Audio analytics.

## 4. Personas

| Persona | Description | Top needs |
|---|---|---|
| **Ravi — Security Operator** | Watches the live wall during a shift; responds to alerts | Clear, low-noise alerts; fast "show me where" search; one-click clip review |
| **Meera — Security Supervisor** | Owns site security; reviews incidents and shift reports | Trustworthy incident reports, daily summaries, PDF export, trends |
| **Arjun — Investigator** | Reconstructs what happened after an incident | Multi-camera timeline, implicit search, Q&A over the archive, evidence export |
| **Admin** | Sets up cameras, zones, topology, users | Simple configuration, health visibility |
| *Evaluator (guide / recruiter)* | Assesses the system | Live demo, measurable results, clean architecture |

## 5. Key user journeys

**J1 — Live alert to incident report (Ravi → Meera)**
1. A person enters a restricted zone after hours on cam02, then appears on cam04 40 s later.
2. The rule engine flags intrusion; the VLM gate verifies it; an alert appears on Ravi's dashboard within seconds.
3. The correlation service links cam02 and cam04 events into one group.
4. When the group closes, the reasoning pipeline segments phases, captions each phase per view, and synthesizes an incident report.
5. Meera opens the report, reads the causal chain with linked clips, and exports a PDF.

**J2 — Implicit search (Arjun)**
1. Arjun types "someone left a bag near the entrance and walked away this morning".
2. The system decomposes the query, filters candidates by embeddings and metadata, reasons over twin data, and fetches extra VLM evidence where needed.
3. Results show ranked clips with a relevance score, a short reasoning trace and a mask on the bag. One click opens playback at that moment.

**J3 — Image search (Arjun)**
1. Arjun crops a person from a paused frame and clicks "Find similar".
2. Matching tracks across cameras appear, ordered by time.

**J4 — Ask the archive (Meera)**
1. "How many after-hours intrusions happened this week, and which camera had the most?"
2. The assistant calls tools (events query, search), answers with numbers and citations, and follows up: "Show me the worst one" opens the incident.

**J5 — Daily report (Meera)**
1. At 07:00 the daily report job aggregates the last 24 h and writes a narrative summary with charts; Meera downloads the PDF.

**J6 — Setup (Admin)**
1. Adds 6 RTSP cameras, draws zones on snapshots, defines topology edges (overlap/transit times), creates operator accounts.

## 6. Features

Priority uses MoSCoW. Phase refers to `backlog.md`.

| ID | Feature | Description | Priority | Phase |
|---|---|---|---|---|
| F-01 | Auth & RBAC | JWT login, refresh; roles admin/operator/viewer | Must | 1 |
| F-02 | Camera management | CRUD RTSP cameras, site/location metadata, status | Must | 1 |
| F-03 | Live ingestion & recording | Pull RTSP, record 10 s segments, keyframes, publish to Kafka | Must | 1 |
| F-04 | Live camera wall | 1/4/6-tile grid, low-latency HLS/WebRTC | Must | 1 |
| F-05 | Perception & digital twin | Detection, tracking, attributes, zones, SigLIP embeddings → twin JSON | Must | 2 |
| F-06 | Indexing | Twin → PostgreSQL + Qdrant | Must | 2 |
| F-07 | Playback & overlays | Time-range playback, detection-density scrubber, bbox overlays | Must | 2 |
| F-08 | Event detection | Rules: intrusion, loitering, crowding, abandoned object, running; VLM verification | Must | 3 |
| F-09 | Zones & topology config | Polygon editor, camera graph editor | Must | 3 |
| F-10 | Multi-camera correlation | Time-aligned linking via topology into correlation groups | Must | 3 |
| F-11 | Real-time alerts | WebSocket alerts, ack/resolve; email/Telegram plugins disabled by config | Must | 3 |
| F-12 | LLM provider switching | `local`/`hybrid`/`cloud` profiles, model registry | Must | 3 |
| F-13 | Text search (reasoning) | Decomposition → coarse hybrid retrieval → LLM rerank + trace → JIT refinement | Must | 4 |
| F-14 | Image search | Crop/upload → similar tracks across cameras | Must | 4 |
| F-15 | Object-level grounding | SAM 2.1-tiny masks on result frames | Should | 4 |
| F-16 | Phase-aware event reasoning | Fine-tuned TG + PhaVR adapters, multi-view evidence bundle | Must | 5 |
| F-17 | Incident reports | LLM synthesis → validated JSON → UI + PDF, similar past incidents | Must | 6 |
| F-18 | RAG assistant | Multi-turn, tool-using, streamed, cited answers | Must | 6 |
| F-19 | Daily security reports | Scheduled + on-demand, narrative + charts, PDF | Must | 6 |
| F-20 | Investigation timeline | Multi-camera lanes, synced playback, saved cases | Should | 6 |
| F-21 | Kubernetes local deployment | minikube + Kustomize, GPU scheduling | Must | 7 |
| F-22 | Cloud Docker deployment | Single-VM Compose, TLS, CI/CD images | Must | 7 |
| F-23 | Observability | Prometheus metrics, Grafana dashboards | Should | 7 |
| F-24 | Evaluation suite | Retrieval, reasoning, response quality, latency, usability harnesses | Must | 4, 5, 7 |

## 7. Success metrics

Targets are initial and will be recalibrated once Phase 2 and Phase 4 baselines exist. Measurement methods are in `SRS.md §6` and `design_architecture.md §13`.

| Area | Metric | Target |
|---|---|---|
| Retrieval | Recall@5 on implicit-query benchmark | ≥ 0.60 |
| Retrieval | Recall@10 on explicit-query benchmark | ≥ 0.80 |
| Retrieval | Improvement of full pipeline over embedding-only baseline (R@1) | ≥ +20 pts |
| Reasoning | Phase-segmentation mIoU gain, fine-tuned vs zero-shot base | ≥ +0.15 |
| Reasoning | VQA accuracy gain, fine-tuned vs base | ≥ +10 pts |
| Response quality | RAG faithfulness (judge + human spot check) | ≥ 0.85 |
| Response quality | Citation precision | ≥ 0.90 |
| Response quality | Incident report schema-valid after ≤ 2 retries | ≥ 98 % |
| Response quality | Incident report human rubric (1–5, accuracy/completeness/causality/actionability) | ≥ 3.8 avg |
| Latency | Live ingest → indexed (p95, 4 cameras) | ≤ 30 s |
| Latency | Event → dashboard alert (p95, rules + VLM gate) | ≤ 30 s |
| Latency | Search response (p95, hybrid profile) | ≤ 6 s; coarse-only ≤ 1 s |
| Latency | Incident report ready after group close (p95) | ≤ 3 min |
| Usability | System Usability Scale (SUS), ≥ 8 participants | ≥ 70 |
| Usability | Task time "find incident X" vs manual scrubbing | ≥ 50 % reduction |
| Reliability | No message loss across consumer restarts (at-least-once + idempotency) | 0 lost segments in chaos test |

## 8. Release plan

| Phase | Weeks | Milestone / demo |
|---|---|---|
| 1 | 1–2 | **Phase II review:** live multi-camera streams through Kafka, recorded to storage, visible on the dashboard with login |
| 2 | 3–4 | Detections and tracks on playback; twin indexed in Postgres/Qdrant |
| 3 | 5–6 | Live verified alerts, multi-camera correlation, zones/topology editors; annotation starts |
| 4 | 7–8 | Text and image search with reasoning traces and masks; retrieval baseline numbers |
| 5 | 9–10 | Fine-tuned phase reasoning with evaluation numbers |
| 6 | 11–12 | Incident reports, RAG assistant, daily reports, investigation timeline — **feature complete** |
| 7 | 13–14 | Kubernetes + cloud deployment, full evaluation, hardening — **final demo** |

## 9. Assumptions and dependencies

- Kuldeep and Pankaj deliver phase annotations (≈ 200–300 clips) by end of week 9 and retrieval ground truth by end of week 8.
- Free GPU quotas on Kaggle/Colab remain available (≈ 30 GPU-h/week per Kaggle account — verify).
- Free-tier LLM APIs remain available; the system must still work fully in `local` profile.
- MEVA, WILDTRACK, UCF-Crime and ShanghaiTech Campus are obtainable for research use.
- Laptops have ≥ 16 GB RAM (else `lite` profile with fewer cameras).

## 10. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Annotation not ready for fine-tuning | High | High | Start guideline in P3; pseudo-label drafts; minimum viable set of 150 clips; zero-shot fallback path always works |
| 4 GB VRAM insufficient for concurrent models | High | Medium | GPU lease, 4-bit quantization, frame/pixel caps, split perception/reasoning across two laptops, cloud profile |
| 3B local LLM quality too low for reranking/RAG | Medium | Medium | `hybrid` profile uses free cloud models for reasoning; evaluation reports both |
| Free API rate limits during demo | Medium | High | Response caching, pre-warmed demo queries, local fallback |
| Kubernetes GPU passthrough on Windows/WSL2 fails | Medium | Medium | GPU workloads run outside cluster, reached via `ExternalName` service (documented fallback) |
| Scope too large for 14 weeks | Medium | High | MoSCoW; "Should" features cut first; phase demos keep a working system at every step |
| Contract drift between tracks | Medium | Medium | Contract-first freeze at each phase start; shared fixtures; CI schema tests |

## 11. Future work
Cross-camera re-identification with appearance embeddings; depth-aware twins; pose/gaze modalities; audio events; email/Telegram delivery; edge deployment on Jetson-class devices; on-device distillation of the reasoning adapters; multi-site federation.
