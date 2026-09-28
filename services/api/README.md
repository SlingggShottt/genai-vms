# api

Auth/RBAC, CRUD, recordings playlists, alerts (Kafka to WebSocket), notifier plugins, BFF proxy to retrieval/reasoning, audit.

| | |
|---|---|
| **Owner** | Jatin |
| **Port** | 8000 |
| **Topics** | consumes vms.events.v1, vms.correlations.v1, vms.incidents.v1 (land with P3-J3) |
| **Config** | `src/api/settings.py` via `vms_common.config` (pydantic-settings) — never `os.environ` directly |
| **Metrics** | `/metrics` (Prometheus text format) — endpoint-specific metrics land as each area is implemented; see `docs/design_architecture.md §15` |

## Run

```bash
make migrate                              # apply libs/vms_db Alembic history
uv run --package vms-api uvicorn api.main:app --reload --port 8000
```

`GET /health` (liveness), `GET /ready` (checks Postgres), `GET /metrics`.

## Implemented (P1-J1)

FastAPI app factory (`create_app` in `main.py`), style_guide.md §A.5 error
envelope for `APIError` / validation / HTTP / unhandled exceptions
(`api/errors.py`), request-id middleware (`api/middleware.py`), request-scoped
DB session dependency (`api/deps.py`), async engine lifecycle tied to the app
lifespan. `libs/vms_db` owns the `core` schema models (`users`,
`refresh_tokens`, `cameras`, `audit_log`) and migration `0001`.

Not yet implemented: auth/RBAC (P1-J2), camera management (P1-J3) and
everything else in `docs/design_architecture.md §9` — see `docs/backlog.md`.
`docs/style_guide.md §A.1` for the layout (`domain/` has no I/O and is where
unit tests target; `adapters/` wraps DB/S3/Qdrant/gateway; services never
import another service, only `libs/*`).
