# indexer

Idempotent writes of one `twinready.v1` message + its twin document into
PostgreSQL (`media.segments`, `vision.tracks`, `vision.track_segments`,
`vision.minute_counts`) and Qdrant (`frames`, `tracks` vector collections).
Consumes `vms.twin.v1` (design_architecture.md §5.2 — topic is singular
"twin", the message `schema_version` is `twinready.v1`).

| | |
|---|---|
| **Owner** | Jatin |
| **Port** | none (internal only) |
| **Topics** | consumes `vms.twin.v1`; DLQ on `vms.dlq.v1` after 3 failed attempts |
| **Config** | `src/indexer/settings.py` — `VMS_INDEXER_*` plus the shared `VMS_KAFKA_*` / `VMS_STORAGE_*` / `VMS_DB_*` / `VMS_QDRANT_*` blocks |
| **Compose** | `deploy/compose/docker-compose.yml`, profile `core` |

## Design

- `domain/segment_key.py` — pure re-derivation of the segment video's
  `s3://` URI from `(camera_id, start_ts, segment_id)`. `twinready.v1`
  doesn't carry that URI (only `twin_uri`/`embeddings_uri`), and services
  never import another service's code, so this mirrors ingestion's key
  layout convention (design_architecture.md §6.3) rather than importing it.
- `domain/minute_counts.py` — pure per-(minute, category) max-simultaneous
  object count from one twin's frames, for `vision.minute_counts`.
- `adapters/repository.py` — the actual upserts. `media.segments` and
  `vision.track_segments` are plain "insert or overwrite the row you were
  given" upserts, keyed so a replayed message is a no-op. `vision.tracks`
  is different: rather than incrementally merging one segment's contribution
  into the existing row (fiddly to make idempotent *and* order-independent
  for JSONB/array fields), it's **fully recomputed** from every
  `vision.track_segments` row for that `track_id` on each write. That
  costs one extra query per track per segment but is trivially idempotent
  and correct regardless of processing order. `vision.minute_counts.count`
  merges across segments sharing a minute with `GREATEST`, which is a
  reasonable approximation of a whole-minute simultaneous max (each
  segment only sees its own ~10s window) and a no-op on exact replay.
- `worker.py` — `IndexerConsumer(BaseConsumer[TwinReadyV1])`: fetch the twin
  JSON from S3, run every Postgres upsert inside one DB transaction
  (`vms_db.session.session_scope`), then fetch the segment's `.npz`
  embeddings and upsert them into Qdrant. Both stores are written
  idempotently, so if either step fails, `BaseConsumer`'s retry just redoes
  the whole `handle()` safely — no separate two-phase-commit machinery.
- `vms_common.qdrant` (shared with retrieval's later read side —
  design §6.2 notes "query side: D") — `collections.py` creates `frames`,
  `tracks`, and an empty `knowledge` collection with their vector configs
  and payload indexes (idempotent, same shape as `create_topics.sh`'s
  `--if-not-exists`); `point_ids.py` derives deterministic UUID5 point ids
  from `(segment_id, frame_idx)` / `(track_id, segment_id)`, so a replayed
  message's `upsert` overwrites the same point instead of duplicating it —
  Qdrant needed no extra idempotency bookkeeping the way Postgres did.
  `indexer/domain/qdrant_payloads.py` shapes the payload dicts.
- **Simplification, documented rather than hidden**: `tracks` collection
  points are per `(track_id, segment_id)` — one point per segment a track
  appears in, not one point merged across its whole life. Recomputing a
  single track-spanning point (matching `vision.tracks`' own Postgres
  approach) would need a payload read-merge-write on `segment_ids[]` and
  deciding which segment's crop embedding "wins"; out of scope for this
  smoke-test-scale story. Retrieval can merge points by `track_id` later if
  it wants one hit per track.
- `frame.idx` (the `Frame.idx` field, not a separately stored lookup) is
  used directly as the row index into the segment's `.npz` `frame_vectors`
  — safe because perception assigns `idx` sequentially over every sampled
  frame (0, 1, 2, ... no gaps) and embeds every sampled frame in that same
  order, confirmed by reading `services/perception/src/perception/adapters/decoder.py`
  and `worker.py`. `TrackSummary.embedding_index` does the equivalent job
  for tracks — it's already in the twin.v1 contract for exactly this.

Bootstrap the collections once, independent of running the service:
`make qdrant-collections` (needs `make up PROFILE=infra` first) — same
pattern as `make topics`, and the script's `ensure_collections` call is the
same idempotent function `main.py` also calls at indexer startup.

## Testing

- Unit: `domain/` functions only (no I/O) — segment key layout, minute-count
  bucketing/max logic, Qdrant payload shaping. `make test SVC=indexer`.
- Integration (`make test-int`, needs Docker) — **verified for real**, not
  just written:
  - Postgres: applies the Alembic history to a throwaway container and
    calls `index_twin` twice with the shared fixture
    (`libs/vms_common/src/vms_common/fixtures/{twin,twinready}_v1.json`) to
    assert replay doesn't duplicate rows (P2-J1 AC: 1 row each in segments/
    tracks/track_segments/minute_counts after two runs), plus one test that
    the indexed rows' content matches the twin document.
  - Qdrant (`test_qdrant_indexing.py`, container pinned to
    `qdrant/qdrant:v1.11.5` to match compose): bootstrap creates all three
    collections with the right vector config, is idempotent to call twice,
    `index_embeddings` on the shared fixture's twin + `embeddings.npz`
    twice leaves exactly 1 point per collection (P2-J2 AC), and a
    `camera_id` + `ts`-range filtered query returns exactly that point
    while a mismatched `camera_id` returns none.

Not run against a live Kafka topic — the consumer wiring (`worker.py`/
`main.py`) follows the same `BaseConsumer` pattern perception already uses
against real Kafka, but only the DB/Qdrant write paths themselves have been
exercised against real stores here. Verify with
`make up PROFILE=infra,core,perception` + `make sim` before trusting the
end-to-end path.
