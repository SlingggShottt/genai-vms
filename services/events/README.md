# events

Sliding per-camera state over twins; rule engine; candidate to VLM-verified event; persistence.

| | |
|---|---|
| **Owner** | Divyansh |
| **Port** | none (internal only) |
| **Topics** | consumes `vms.twin.v1` (`twinready.v1`); will produce `vms.events.v1` with P3-D4 |
| **Config** | `src/events/settings.py` via `vms_common.config` (pydantic-settings) — never `os.environ` directly; rule thresholds in [`config/rules.yaml`](../../config/rules.yaml) |
| **Tables** | writes `events.candidates` (migration `0004`) |
| **Metrics** | `vms_events_candidates_total{rule}` (defined; no scrape endpoint yet — the service has no HTTP port) |

## Status

**P3-D1:** the rule engine, debounce/extension and candidate persistence.
**P3-D2:** the camera-wide `abandoned_object` and `running` rules, and JSON Schemas
for every rule's params. **Not yet:** VLM verification (P3-D4), `events.events` and
the `vms.events.v1` / `event.v1` publication (P3-D4), and the precision/recall check
of the rules on labelled clips (P3-D2's third criterion — it needs the labelled
ShanghaiTech/MEVA clips, which aren't on this machine).

## What it does

For every `twinready.v1` it fetches the segment's twin from object storage,
replays the sampled frames through the enabled rules and upserts the resulting
**candidates** — rule hits, before verification — into `events.candidates`.

```
twinready.v1 ─▶ fetch twin (S3) ─▶ engine.process_twin ─▶ upsert candidates ─▶ save state ─▶ commit offset
                                        ▲                                          │
                              per-camera state (Redis) ◀───────────────────────────┘
```

Rules come in two kinds. **Zone rules** work on the zones of a camera: the twin
lists, for every detected object, the *names* of the zones it stands in (stamped by
perception from the same zone source); this service looks the zones up again for
their type and schedule, and a camera with no zones raises no zone-rule candidates.
**Camera-wide rules** look at the whole view, need no zones, and their candidates
have a NULL zone.

| Rule | Fires when | Defaults | Severity |
|---|---|---|---|
| `intrusion.restricted` | a person/vehicle is in a `restricted` zone | `min_frames: 2` | high |
| `intrusion.after_hours` | a person is in a zone **outside its schedule** (the schedule is the zone's normal hours, site-local) | `min_frames: 2` | high |
| `loitering` | the same track stays in a zone | `dwell_s: 60` | medium |
| `crowding` | strictly more than `max_persons` people in a zone | `max_persons: 8`, `duration_s: 20` | medium |
| `abandoned_object` *(camera-wide)* | a bag/suitcase has stayed within `static_epsilon` of where it came to rest for `static_s` **and** no person was within `owner_radius` for `unattended_s` | `static_s: 30`, `unattended_s: 20`, `owner_radius: 0.08`, `static_epsilon: 0.03` | high |
| `running` *(camera-wide)* | a person is faster than `speed` (frame fractions per second, as perception measures it) in `min_samples` samples | `speed: 0.35`, `min_samples: 3`, `debounce_s: 2` | low |

All rules also take `debounce_s` (5; 2 for `running`), `categories`, and
(loitering/crowding) `zone_types`; `abandoned_object` also takes `owner_categories`.
Camera-wide rules can be overridden per camera but not per zone (rejected at load). Thresholds and per-camera / per-zone overrides live in
`config/rules.yaml` (precedence: rule defaults < camera < zone < camera+zone;
the file is validated when the service starts, so a typo stops it with a clear
message). An unlisted rule is **enabled** with its built-in defaults.

### Candidates: debounce and extension

A rule only says "this holds in this frame". The engine folds consecutive hits
of the same *(camera, rule, zone, track)* into an **episode**:

* a hit extends the open episode if it comes within `debounce_s` of the previous
  one — a detection flicker doesn't split a stay in two;
* it becomes a **candidate** once it spans the rule's required frames / duration
  (≥ `min_frames` hits; ≥ `dwell_s` / `duration_s` of presence) — thresholds are
  inclusive;
* while the condition keeps holding, each new segment extends the candidate
  (`end_ts` moves, status stays `open`); after `debounce_s` of quiet it is
  `closed` — it never reopens, a new stay is a new candidate;
* episodes that never reach their threshold leave no trace.

`abandoned_object` remembers, per bag, where it first came to rest, when, and when a
person was last near it — in a per-rule scratchpad saved with the camera's state, so a
restart mid-wait loses nothing. It reports once both durations have elapsed but
**dates the candidate from when the object became unattended** (usually when the owner
walked away), the moment worth showing. Consequently a candidate's `start_ts` can be
earlier than the first segment in its `segment_ids` (which lists the segments that
contained hits): select footage by `start_ts`/`end_ts`, not by `segment_ids` alone. It
cannot tell whose bag it is — anyone within the radius counts as attending it — and a
tracker that loses and re-finds the bag under a new id restarts its clock. On the demo
footage (a busy street) the defaults raise neither `running` (the 99th-percentile
walking speed is 0.083, the fastest 0.175) nor `abandoned_object`; both fire only with
relaxed thresholds, which is how their plumbing was verified.

`rule_score` is a heuristic in [0, 1] (detection confidence; headcount-based for
crowding), not a calibrated probability. `details` records the frame count,
duration, per-episode peaks and the effective params used.

### Delivery guarantees

Kafka is at-least-once, so everything is replay-safe:

* the candidate id is deterministic — a UUIDv5 of `(camera, rule, zone, track,
  start_ts)` (design §15) — and the upsert is monotonic (`end_ts`/score only
  grow, ids are unioned, `closed` is final), so a redelivered twin changes
  nothing;
* per-camera state is checkpointed in Redis (`events:state:<camera>`) **after**
  the candidates are written, and twins at or before the saved
  `last_segment_end` are skipped. A crash between the two replays the twin to the
  same result; a restart resumes a half-finished stay instead of restarting its
  dwell clock;
* if Redis state is lost, a stay in progress restarts its clock (and gets a new
  candidate id) — acceptable, and logged as `events_state_unreadable_starting_fresh`
  when a stored document can't be read.

## Run

```bash
make migrate                      # needs 0004 (events.candidates)
make up PROFILE=infra,core        # builds and starts the events container
# or on the host:
uv run --package vms-events events
```

Needs `config/rules.yaml` (shipped) and the camera zones (`config/zones.yaml`
fallback, or the API once it is a Compose service — see `config/zones.example.yaml`).

| Env var | Default | |
|---|---|---|
| `VMS_EVENTS_RULES_PATH` | `config/rules.yaml` | restart to apply edits |
| `VMS_EVENTS_SITE_TIMEZONE` | `Asia/Kolkata` | zone schedules are site-local `HH:MM` |
| `VMS_EVENTS_API_BASE_URL` / `VMS_EVENTS_SERVICE_TOKEN` | unset | zones from `GET /internal/v1/zones`, else the YAML |
| `VMS_EVENTS_ZONES_YAML_FALLBACK` | `config/zones.yaml` | refreshed every 60 s |
| `VMS_EVENTS_CONSUMER_GROUP` | `events` | |
| `VMS_EVENTS_STATE_TTL_SECONDS` | 7 days | Redis TTL of a silent camera's state |

Plus the shared `VMS_KAFKA_*`, `VMS_STORAGE_*`, `VMS_DB_*`, `VMS_REDIS_*` blocks.
Look at the results with:

```sql
select rule_id, camera_id, zone_name, severity, status, start_ts, end_ts, track_ids
from events.candidates order by start_ts desc limit 20;
```

## Adding a rule

See `CLAUDE.md` ("New event rule"): a module in `src/events/domain/rules/` with
`@rule("<id>")` and a `Params` model, imported in `rules/__init__.py`; defaults
in `config/rules.yaml`; positive and negative tests with synthetic twin
sequences (`tests/conftest.py` has the builders). Subclass `ZoneRule` (judge the
objects in one zone) or `CameraRule` (judge the whole frame, with a JSON-serialisable
`memory` that is saved with the camera's state). A rule is a pure function of one
frame — the engine handles debouncing and extension.

Every rule's params have a JSON Schema, and the whole `rules.yaml` has one too,
generated from the registry into `config/rules.schema.json` (editors pick it up through
the `# yaml-language-server` line in `rules.yaml`). After adding a rule or changing
params run

```bash
uv run --package vms-events python -m events.schema_export --write   # --check to verify
```

— a unit test fails while the committed schema is stale.

## Layout

`domain/` is pure (no I/O) and holds nearly all the tests; `adapters/` wraps
Postgres, Redis, the zones source and the YAML loader.

```
domain/  rules/ (base registry + the six rules) · config.py · schedule.py
         state.py · candidates.py · engine.py · schema.py
adapters/ candidate_repository.py · state_store.py · zones_source.py · rules_loader.py
worker.py (Kafka consumer) · main.py · settings.py · metrics.py · schema_export.py
```

Tests: `make test SVC=events` (unit); `make test-int` for the Postgres-backed
integration tests (needs Docker).
