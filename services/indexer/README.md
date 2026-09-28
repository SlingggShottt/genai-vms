# indexer

Idempotent writes of segments, tracks, event captions and incident sections into PostgreSQL + Qdrant.

| | |
|---|---|
| **Owner** | Jatin |
| **Port** | none (internal only) |
| **Topics** | consumes vms.twin.v1, vms.events.v1, vms.incidents.v1 |
| **Config** | `src/indexer/settings.py` via `vms_common.config` (pydantic-settings) — never `os.environ` directly |
| **Metrics** | TBD when implemented — see `docs/design_architecture.md §15` for the `vms_` metrics this service must expose |

Not implemented yet — this is the P1-D1 scaffold. See `docs/backlog.md` for
the story that fills this in, and `docs/style_guide.md §A.1` for the layout
(`domain/` has no I/O and is where unit tests target; `adapters/` wraps DB/S3/
Qdrant/gateway; services never import another service, only `libs/*`).
