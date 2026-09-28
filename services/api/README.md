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

Set `VMS_ADMIN_PASSWORD` (and optionally `VMS_ADMIN_EMAIL`) before first
start to seed the admin account; leave it empty to skip seeding.
`VMS_JWT_SECRET` and `VMS_API_SERVICE_TOKEN` must both be set to real values
— empty rejects everything rather than accepting anything (see
`vms_common.auth` and `api.api.security.require_service_token`).

## Implemented

**P1-J1** — FastAPI app factory (`create_app` in `main.py`), style_guide.md
§A.5 error envelope for `APIError` / validation / HTTP / unhandled
exceptions (`api/errors.py`), request-id middleware (`api/middleware.py`),
request-scoped DB session dependency (`api/deps.py`), async engine lifecycle
tied to the app lifespan. `libs/vms_db` owns the `core` schema models
(`users`, `refresh_tokens`, `cameras`, `audit_log`) and migration `0001`.

**P1-J2** — `POST /auth/login`, `/auth/refresh` (rotates the refresh token),
`/auth/logout`, `GET /auth/me`; Argon2id password hashing
(`domain/security.py`, offloaded to a thread — it's deliberately slow);
access-token JWT encode/decode in `vms_common.auth` (shared, not
api-specific); `require_role(*roles)` and `require_service_token`
dependencies (`api/security.py`); admin-account seeding on first start
(`adapters/users.py::seed_admin_user`); users CRUD at `/users` (admin only);
audit entries for login/logout/refresh/user-changes, written in their own
committed transaction (`adapters/audit.py`) so they survive even when the
handler that triggered them goes on to raise/roll back.

Not yet implemented: camera management (P1-J3) and everything else in
`docs/design_architecture.md §9` — see `docs/backlog.md`.
`docs/style_guide.md §A.1` for the layout (`domain/` has no I/O and is where
unit tests target; `adapters/` wraps DB/S3/Qdrant/gateway; services never
import another service, only `libs/*`).
