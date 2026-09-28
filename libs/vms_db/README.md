# vms_db

SQLAlchemy 2 (async) models + one Alembic history for the single `vms`
Postgres database, one schema per domain. `Base` (`base.py`), the async
engine/session factory (`session.py`) and migration `0001` (`core` schema:
`users`, `refresh_tokens`, `cameras`, `audit_log`) landed in P1-J1; table
ownership within each schema follows `docs/design_architecture.md §6.1`.
Connection DSN comes from `vms_common.config.DatabaseSettings` (`VMS_DB_DSN`)
— never hardcoded in `alembic.ini`.

```bash
make migrate                          # alembic upgrade head
make migration MSG="add zones"        # alembic revision --autogenerate
```

| Schema | Owner |
|---|---|
| `core` (users, cameras, zones, topology, alerts, audit, cases) | J |
| `media` (segments, gaps) | J |
| `vision` (tracks, track_segments, minute_counts) | J |
| `events` (candidates, events) | D |
| `events` (correlation_groups, correlation_links) | J |
| `reasoning` (jobs, incidents, incident_notes) | D |
| `reasoning` (daily_reports) | J |
| `retrieval` (search_logs, jit_cache) | J |
| `retrieval` (chat_sessions, chat_messages) | D |

Never edit an already-merged migration (`CLAUDE.md`); add a new one instead.
