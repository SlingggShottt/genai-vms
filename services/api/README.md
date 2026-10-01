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

**P1-J3** — Camera CRUD at `/cameras` (admin write, any role read);
`GET /cameras/status` merges live Redis heartbeats
(`adapters/camera_status.py`) with `core.cameras`; `GET /internal/v1/cameras`
for ingestion/perception (service-token gated, `api/internal.py`).

**P2-J4** — Zone CRUD (`api/zones.py`): `GET/POST /cameras/{id}/zones`,
`PATCH/DELETE /zones/{id}` (admin write, any role read); `core.zones`
(migration `0003`) FKs to `core.cameras.id`, `ondelete=CASCADE`. Polygon
validation (3-32 points, normalized to `[0,1]`, `api/domain/zones.py`) is
pure and shared between create/update. `GET /internal/v1/zones` added to
`api/internal.py` — its `camera_id` is the camera's **code**, not the UUID
`id` the public zones router uses (perception/events only ever see camera
codes, from `segment.v1`; same split `CameraInternal` already has for
cameras). `libs/vms_common/contracts/zones.py` (P2-D3's proposed day-1
contract) needed no field changes, just its docstring updated now that
it's the real thing.

**P2-J3** — Recordings & twin overlay endpoints, all roles read
(`api/recordings.py`, `api/twin.py`):
- `GET /recordings/{camera_id}/segments` — `media.segments` in `[start,
  end)`, each with a presigned GET url, interleaved with explicit `gap`
  markers for uncovered time (never a silent skip).
- `GET /recordings/{camera_id}/playlist.m3u8` — the same timeline as an
  HLS VOD playlist; every segment after the first is preceded by
  `#EXT-X-DISCONTINUITY` (ingestion's segmenter uses `-reset_timestamps 1`,
  so each `.ts` starts its own clock, and a recording gap is one too —
  without it hls.js ends playback early on a seek past the buffered range),
  and every segment gets its own `#EXT-X-PROGRAM-DATE-TIME`. No
  transcoding — a presigned url always serves its segment's whole `.ts`
  file (`domain/recordings.py`).
- `GET /recordings/{camera_id}/density` — `vision.minute_counts` summed
  across categories and re-bucketed to the requested `bucket` seconds,
  zero-filled (a sparkline needs a continuous series, unlike the
  absence-means-nothing convention `vision.minute_counts` itself uses).
- `GET /twin/{camera_id}/frames` — bboxes/track-ids for a window capped at
  60s, fetched live from each covering segment's twin JSON in S3
  (`adapters/twin_frames.py`) — Postgres only has track *summaries*, not
  per-frame boxes.
- `camera_id` in all four is the camera's `code` (e.g. `cam03`), matching
  what `media.segments`/`vision.minute_counts` actually store — not the
  UUID `core.cameras.id` the rest of this router uses elsewhere.
- Needs `storage: StorageSettings` (`VMS_STORAGE_*`) — new for this
  service as of P2-J3, wired as `app.state.s3` in `main.py`'s lifespan,
  same shape as `app.state.redis_client`.

**P2-J6** — `GET /tracks/{track_id}` (`api/tracks.py`), all roles read:
side-panel data for the frontend's detection overlay (P2-J6's click-a-box
AC) — category, first/last seen, zones visited, attributes, and total
dwell time. `dwell_s` is summed from every `vision.track_segments` row for
that track (`adapters/tracks.py`) rather than read off `vision.tracks`
itself, since a track can leave and re-enter frame within its overall
`first_ts`/`last_ts` span, so only the per-segment rows know actual time
in view.

Not yet implemented: everything else in `docs/design_architecture.md §9`
— see `docs/backlog.md`.
`docs/style_guide.md §A.1` for the layout (`domain/` has no I/O and is where
unit tests target; `adapters/` wraps DB/S3/Qdrant/gateway; services never
import another service, only `libs/*`).
