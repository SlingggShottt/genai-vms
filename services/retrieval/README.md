# retrieval

Text search pipeline (decompose, coarse retrieval, LLM rerank), image search, JIT refinement, RAG assistant.

| | |
|---|---|
| **Owner** | Divyansh + Jatin (modules — see CODEOWNERS) |
| **Port** | 8010 |
| **Topics** | HTTP only (no Kafka consumption) |
| **Config** | `src/retrieval/settings.py` via `vms_common.config` (pydantic-settings) — never `os.environ` directly |
| **Metrics** | TBD when implemented — see `docs/design_architecture.md §15` for the `vms_` metrics this service must expose |

Not implemented yet — this is the P1-D1 scaffold. See `docs/backlog.md` for
the story that fills this in, and `docs/style_guide.md §A.1` for the layout
(`domain/` has no I/O and is where unit tests target; `adapters/` wraps DB/S3/
Qdrant/gateway; services never import another service, only `libs/*`).
