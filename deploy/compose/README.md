# Compose deployment

Local dev and demo stack. Profiles per `docs/design_architecture.md §12.1`.
Only `infra` exists so far (P1-D3); `core`, `perception`, `genai`, `tools`,
`obs`, `lite` land with the stories that build those services, and
`docker-compose.prod.yml` (cloud VM) lands in P7-J2.

## Run

```bash
cp ../../.env.example ../../.env   # fill in secrets first — see .env.example
make up PROFILE=infra              # from the repo root
make topics                        # create the vms.* Kafka topics
make down
```

| Service | URL |
|---|---|
| Kafka (host clients) | `localhost:9092` |
| kafka-ui | http://localhost:8080 |
| Postgres | `localhost:5432` |
| Qdrant | http://localhost:6333/dashboard |
| Redis | `localhost:6379` |
| MinIO API / console | http://localhost:9000 / http://localhost:9001 |
| MediaMTX RTSP / HLS / WebRTC | `rtsp://localhost:8554/<path>` / http://localhost:8888 / http://localhost:8889 |

## Troubleshooting

**MediaMTX shows "unhealthy" but streams work fine.** The healthcheck in
`docker-compose.yml` calls `wget` inside the `bluenviron/mediamtx` image,
which may ship without a shell/wget (unverified — this repo's dev
environment had no Docker daemon available when P1-D3 was written). If
`docker compose ps` shows it permanently unhealthy despite RTSP/HLS/WebRTC
actually working, replace that service's `healthcheck:` block with
`disable: true` and note it in this file.

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
