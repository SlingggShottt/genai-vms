# Compose deployment

Local dev and demo stack. Profiles per `docs/design_architecture.md §12.1`.
Available so far: `infra` (P1-D3), `tools` (camera simulator), `core`
(ingestion, indexer, events) and `perception` (GPU). `genai`, `obs` and `lite` land
with the stories that build those services, and `docker-compose.prod.yml`
(cloud VM) lands in P7-J2. The API is not a compose service yet — run it on
the host (`uv run --package vms-api uvicorn api.main:app --port 8000`).

## Run

```bash
cp ../../.env.example ../../.env   # fill in secrets first — see .env.example
make up PROFILE=infra              # from the repo root
make migrate && make topics && make qdrant-collections
make down
```

Use `make` rather than calling `docker compose` by hand: Compose reads `.env`
from this directory, not the repo root, so `make` passes the root `.env`
explicitly (`--env-file`). Without it you get "required variable
POSTGRES_PASSWORD is missing a value". Calling Compose directly:
`docker compose --env-file .env -f deploy/compose/docker-compose.yml …` from
the repo root.

| Service | URL |
|---|---|
| Kafka (host clients) | `localhost:9092` |
| kafka-ui | http://localhost:8080 |
| Postgres | `localhost:5432` |
| Qdrant | http://localhost:6333/dashboard |
| Redis | `localhost:6379` |
| MinIO API | http://localhost:9000 (S3 only — see the note below on the console) |
| MediaMTX RTSP / HLS / WebRTC | `rtsp://localhost:8554/<path>` / http://localhost:8888 / http://localhost:8889 |

## Troubleshooting

**MediaMTX "unhealthy", or `dependency failed to start: container
vms-mediamtx is unhealthy`.** Plain `bluenviron/mediamtx:latest` is a scratch
image with no shell and no `wget`, so a compose healthcheck can never pass —
and `ingestion` / `camera-sim` wait for MediaMTX to be healthy, so they refuse
to start. `docker-compose.yml` therefore uses the Alpine-based
`bluenviron/mediamtx:latest-ffmpeg` (same MediaMTX version, ships `wget`);
verified healthy. If you ever switch back to the plain image, also change
those `depends_on` conditions.

**No MinIO web console on :9001.** The pinned `bitnamilegacy/minio:latest` is
a `DEVELOPMENT.2025-05-24` build that serves no console (verified: only
`:9000` listens inside the container, and the binary has no WebUI code — it
looks like MinIO dropped the console from its community builds in 2025). Port
9001 is mapped but nothing answers. Inspect storage with the bundled client:

```bash
docker exec vms-minio mc ls local/                          # buckets
docker exec vms-minio mc ls local/vms-segments/cam01/       # objects
docker exec vms-minio mc du local/vms-keyframes             # size, object count
```

**Qdrant: "Too many open files (os error 24)", HTTP stops answering, indexer
messages dead-lettered.** Docker 29 / containerd 2.x start containers with a
1024 soft `nofile` limit, which Qdrant exhausts after a few dozen indexed
segments (the container still reports healthy). The `qdrant` service sets
`ulimits.nofile` to 65535. Segments that were dead-lettered meanwhile can be
re-indexed by stopping the indexer, waiting until its consumer group is
inactive (Kafka refuses the reset while the stopped member is still counted —
it can take a minute or two), then rewinding it
(`kafka-consumer-groups.sh --bootstrap-server localhost:9092 --group indexer
--topic vms.twin.v1 --reset-offsets --to-earliest --execute`, run inside the
`vms-kafka` container) and starting it again — the indexer is idempotent. Give
any other service the same `ulimits:` block if it shows this on a long run.

**No `nvidia` runtime in Docker** (`--gpus all` fails with `could not select
device driver "nvidia"`). Confirmed missing on a native-Ubuntu dev laptop
without the NVIDIA Container Toolkit — host driver and `nvidia-smi` fine,
`docker info` lists only `runc` — which blocks the `perception` profile. (The
exact error text wasn't captured there; it's the standard message for this
state.) Either install the toolkit
(https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html,
then `sudo nvidia-ctk runtime configure --runtime=docker` and restart Docker),
or run perception on the host instead — verified working with the repo's
CUDA PyTorch, with everything else in Compose:

```bash
make up PROFILE=infra,core,tools   # then, in another terminal:
uv run --package vms-perception python -m perception.main
```

**`nvidia-smi` inside a container** (needed before running the `perception`
profile in later phases — P2 onward):

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

This must print your GPU (driver version, ≥ 4 GB VRAM) on **both** laptops
before P2-D1 (perception worker) is usable locally. If it fails:

1. Confirm you're inside WSL2 Ubuntu, not native Windows PowerShell
   (`CLAUDE.md` — "Run everything inside WSL2").
2. Install the NVIDIA driver on the **Windows host** (not inside WSL2) —
   WSL2 GPU passthrough uses the host driver directly.
3. Install the NVIDIA Container Toolkit inside WSL2:
   `distribution=$(. /etc/os-release; echo $ID$VERSION_ID)` then follow
   https://docs.nvidia.com/cuda/wsl-user-guide/index.html.
4. Restart Docker Desktop (or the Docker daemon) after installing the
   toolkit.

> Not run against real hardware in this repo yet — both builders should
> confirm this on their own laptops and update this note with what
> actually worked (docs/techstack.md's "verify" convention).

**Kafka KRaft cluster ID.** `CLUSTER_ID` in `docker-compose.yml` is a fixed
dev value baked into the compose file. It only needs to stay stable across
restarts of the same `kafka_data` volume — if you wipe that volume, the
existing value still works fine for a fresh cluster.

**Ports already in use.** This stack claims 9092, 8080, 5432, 6333, 6334,
6379, 9000, 9001, 8554, 8888, 8889, 9997. Stop any local Postgres/Redis/etc.
first, or remap the host side of the relevant `ports:` entry.

**MinIO image.** `docker-compose.yml` pins `bitnamilegacy/minio`, not the
official `minio/minio`/`quay.io/minio/minio` — both stopped allowing
anonymous pulls (verified 2026-09-30; see `docs/techstack.md §7`). There's
no separate bucket-creation step anymore either — buckets come from
`MINIO_DEFAULT_BUCKETS` on the `minio` service itself, set on container
start. If MinIO ever needs recreating from scratch, just `docker compose
up -d minio`; no `minio-init` service to wait on.
