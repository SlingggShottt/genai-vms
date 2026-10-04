# correlation

Topology-aware time-aligned linking of verified events across cameras; group open/close.

| | |
|---|---|
| **Owner** | Jatin |
| **Port** | none (internal only) |
| **Topics** | consumes `vms.events.v1` (`event.v1`); produces `vms.correlations.v1` (`correlation.v1`, keyed by `site_id`) |
| **Config** | `src/correlation/settings.py` via `vms_common.config` (`VMS_CORRELATION_*`) — never `os.environ` directly; linking knobs in [`config/correlation.yaml`](../../config/correlation.yaml); camera graph from the api (`GET /internal/v1/topology`) with a [`config/topology.yaml`](../../config/topology.example.yaml) fallback |
| **Tables** | writes `events.correlation_groups`, `events.correlation_links` (migration `0006`) |
| **Metrics** | `vms_correlation_events_total{result}`, `_links_total{edge_type}`, `_groups_closed_total`, `_published_total{status}`, `_open_groups_count`, `_sweep_errors_total` (defined; no scrape endpoint yet — the service has no HTTP port) |

## What it does

Every verified event is a small piece of a story: someone crosses a fence on cam02, shows
up running on cam04 half a minute later. This service puts such events into one **group**
so reasoning (P5) can explain them together and alerts (P3-J3) can show one incident, not
three. An event nothing links to is a group of one — still closed and announced, so a
severe lone event is not lost.

```
event.v1 ─▶ already in a group? ─▶ link to open groups' events ─▶ join / merge / new group ─▶ save ─▶ commit offset
                                                                                                │
                every second:  close groups nothing can still link to  ─▶  announce changed groups ◀┘
                                                                              correlation.v1 ─▶ reasoning, api
```

### Linking (design §7.5)

Two events on **different cameras** link when the camera graph allows it and the score is
high enough. The graph (Settings → camera links) has two kinds of edge:

- **overlap(A, B, τ)** — the cameras see the same area. Each event's window is widened by τ
  on both sides; they link when the widened windows intersect (the gap between the real
  windows is at most 2τ). Fit is 1 when the windows intersect, falling linearly to 0 at 2τ.
- **transit(A → B, min, max)** — B is reachable from A. With *a* the event on A and *b* the
  event on B they link when `start(b) − end(a)` lies in `[min, max]`; fit is 1 at the middle
  of that window and 0 at its bounds. A bidirectional edge also allows the opposite orientation.

`score = fit_weight · fit + compat_weight · compatibility(type_a, type_b)` (0.7 / 0.3) and the
events link at `score ≥ link_threshold` (0.5). Compatibility is a symmetric matrix in
`config/correlation.yaml`; a pair of event types that is not listed is **incompatible** and
never links. If several edges join the same two cameras the best-scoring link is kept. Events on
the same camera never link.

A new event is compared with the events of every **open** group of its site. It joins the
groups it links to — merging them if there are several (union-find): the **oldest** group
survives, absorbs the others' events and links, and each absorbed group is announced once as
`merged` with `merged_into`. `max_group_events` (default 50) is a safety valve: a link that
would grow a group past it is not made.

### Closing and announcing

A group **closes** when its last event ended more than *(the longest transit window — or twice
the largest overlap tolerance — of the edges touching its cameras) + `grace_s`* ago: after that
no neighbouring camera can still produce an event that links. An **open** group is announced when
it is first created and then at most every `publish_throttle_s` (5 s) as it changes; a **closed** or
**merged** group, being final, is announced at once.

## Guarantees

- **At-least-once in, effectively-once out.** An event already in any group (open, closed or
  merged) is ignored on redelivery. Group writes are revision-guarded upserts, so a stale writer
  can never overwrite newer state.
- **Nothing is lost between storing and announcing.** A change is stored first and stays
  `publish_pending` until its message has been acknowledged by Kafka; a crash or outage in between
  costs at most a duplicate message. Consumers key on `group_id` + `revision` (every change bumps
  it) and may drop anything older than what they have seen.
- **Restart-safe.** All state is in Postgres; a restarted service continues the open groups and
  closes whatever came due while it was down.
- **A failed sweep is retried** on the next tick (Kafka or the database may blip); the loop never
  ends on an error.
- **Messages are deterministic**: link order is canonical, scores are rounded to 4 places.

## Limits

- **One instance per consumer group.** The consumer and the sweeper share a lock, which is what
  keeps a close from interleaving with a join (announcing happens *outside* it, so a slow or hung
  Kafka cannot stall event handling). A second replica would need a database-level lock
  (`SELECT … FOR UPDATE` on the open groups) first.
- An event arriving again with a *later* end time or a higher severity (an updated verdict) is
  treated as a duplicate and ignored: links are decided when an event first arrives.
- No appearance/re-identification matching (ADR-008): correlation is by camera graph and time only,
  so a busy scene can over-link and a blind spot between cameras can under-link.
- With no topology (no api, no `config/topology.yaml`) every event is its own group.

## Run

```bash
make migrate                                  # needs migration 0006
cp config/topology.example.yaml config/topology.yaml   # edit to your cameras (or run the api)
make up PROFILE=infra,core                    # starts the correlation container
uv run --package vms-correlation correlation  # or on the host
```

Env (`VMS_CORRELATION_*`): `CONFIG_PATH`, `API_BASE_URL` + `SERVICE_TOKEN` (the camera graph from the
api), `TOPOLOGY_YAML_FALLBACK`, `TOPOLOGY_REFRESH_SECONDS` (60), `SWEEP_INTERVAL_SECONDS` (1),
`CONSUMER_GROUP`, `EVENTS_TOPIC`, `CORRELATIONS_TOPIC`; Kafka and database as everywhere
(`VMS_KAFKA_*`, `VMS_DB_*`). `config/correlation.yaml` is validated at startup — a typo stops the
service with the reason; edit it and restart.

## Tests

```bash
make test SVC=correlation        # 101 unit tests: scoring, engine, config, topology, adapters
make test-int                    # Postgres + Kafka testcontainers: repository, consumer, sweeper, end to end
```

`domain/` is pure (no I/O): scoring, the engine (`add_event`, `close_due`, `due_for_publish`) and the
config model. `adapters/` holds the repository, topology source, config loader and Kafka publisher.
The fixture scenario in `libs/vms_common/fixtures/` (an abandoned bag, an intrusion and a runner that
bridges them) is replayed through the engine and the whole service, and must reproduce
`correlation_v1.json` exactly.
