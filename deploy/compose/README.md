# Compose deployment

Local dev and demo stack. Profiles per `docs/design_architecture.md §12.1`.
Available so far: `infra` (P1-D3), `tools` (camera simulator), `core`
(ingestion, indexer, events) and `perception` (GPU). `genai`, `obs` and `lite` land
with the stories that build those services; `docker-compose.prod.yml` (one cloud VM) is
described under "Cloud VM" at the end of this file.

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

## Cloud VM (production)

`docker-compose.prod.yml` is an overlay on `docker-compose.yml` for one VM: images from GHCR,
Caddy with automatic HTTPS in front, the `cloud` language-model profile (Gemini / Groq), and no
host ports except 80, 443 and 8189/udp. `update.sh` deploys and checks it.

**Status: nothing here has run on a real VM yet.** What was checked on the build machine
(2026-10-07):

- *Configuration:* the merged compose file renders (15 services, no builds, only 80, 443 and 8189/udp
  published); each required variable stops `config` when missing; the Caddyfile validates; MediaMTX takes
  its public address and allowed origins from the environment; the migration command runs in the api
  image; `update.sh`'s logic (order of steps, tag record, a failing migration leaving the record alone,
  rollback, status) against a stub `docker`; both workflows pass `actionlint`.
- *In a real browser (Brave, headless):* the actual Caddyfile in front of the actual `frontend/nginx.conf`
  and a production build of the frontend (media paths `/webrtc` and `/hls` baked in), in Docker on
  `http://localhost:8088` with only the two domain-dependent CSP origins (`https://media.DOMAIN`,
  `wss://DOMAIN`) swapped for `http://localhost:9000` / `ws://localhost:8088` and the `media.` site left
  out. Login, ten pages, an event's clip and pictures from the MinIO origin: **no CSP violation**. A
  WHEP offer through `/webrtc` got 201 with a `Location` under `/webrtc/…`, and the player's DELETE on
  it got 200. The HLS playlist and its variant came back 200 through `/hls`. The assistant's answer
  arrived in pieces (the page grew 7 times in 1.5 s), so the proxy does not buffer server-sent events.
  That test found a real bug: MediaMTX answers HLS first with a 302 to `…/index.m3u8?cookieCheck=1`,
  which lost the `/hls` prefix behind the proxy; the Caddyfile now rewrites it.
- **Not checked:** certificate issuance and HTTPS itself; the `media.DOMAIN` site (presigned URLs through
  Caddy, Host passthrough); playback of HLS in the page (hls.js's `blob:` media) and WebRTC media over
  UDP/NAT; a pull from GHCR; the arm64 images; and what size of VM is enough. First deploy: set
  `CSP_HEADER_NAME=Content-Security-Policy-Report-Only` and read the browser console before enforcing.

### What does not run in the cloud

- **Perception** needs a GPU image (`nvidia/cuda`), so it is not in `COMPOSE_PROFILES` and no new
  digital twins are made on the VM. Run perception on a GPU host that can reach Kafka and MinIO, or
  use **archive mode**: restore a Postgres dump, the Qdrant collections and the MinIO buckets from a
  machine that did the work, then set `VMS_RETRIEVAL_ARCHIVE_SINCE` to the first day you hold footage
  for. Search, the assistant, incident reports and the dashboard then run on what was restored. This
  procedure is described, not rehearsed.
- **Cameras.** RTSP is not published. Reach cameras over a VPN (the ingestion service pulls from the
  camera URLs registered in the app) or run without live cameras.
- **Ollama.** The `cloud` profile sends every language-model task to Gemini or Groq; the phase tasks
  (`phase_tg`, `phase_vr`) run zero-shot on Gemini there, not on the fine-tuned adapters. Frames and
  question text leave the VM for those providers: that is a decision for whoever owns the footage.

### Provisioning

1. A Linux VM with Docker and Compose ≥ 2.24.4 (the overlay uses `!reset` / `!override`; tried with
   5.5.1). Disk: the retrieval image alone is about 9.5 GB on amd64, so start with 60 GB.
   RAM: the build machine runs this stack in about 8 GB without Ollama; that is not a measured
   recommendation for a VM.
2. DNS: an A (and AAAA) record for `DOMAIN` **and** `media.DOMAIN` pointing at the VM, *before* the
   first start. Caddy requests both certificates then; failed attempts count against Let's Encrypt's
   rate limits.
3. Firewall: 80/tcp, 443/tcp, 443/udp, 8189/udp. Nothing else (the databases and Kafka have no host
   ports, but keep it that way at the firewall too).
4. `git clone` the repository to `/opt/genai-vms` (the deploy workflow expects that path; it only needs
   `deploy/` and `config/`).
5. `cp deploy/compose/.env.prod.example .env.prod && chmod 600 .env.prod` and fill in **every**
   secret. A missing one stops `update.sh` with the variable's name.
6. If the images are private: `docker login ghcr.io -u <github-user>` with a token that has
   `read:packages`.

### First start and updates

```bash
cd /opt/genai-vms
./deploy/compose/update.sh 1.0.0      # a tag release.yml published: pull, migrate, topics, start
./deploy/compose/update.sh --status   # every service up, the api answers
./deploy/compose/update.sh --rollback # the tag that ran before the last update
```

The first start of `retrieval` downloads the SigLIP 2 weights into the `hf_cache` volume (a few GB):
`--wait` can take several minutes. Rolling back does **not** undo database migrations; take a backup
before an update that carries one. The same steps run from GitHub: Actions → *Deploy to the VM*
(secrets and the `production` environment are listed at the top of `.github/workflows/deploy.yml`).

Log in with `VMS_ADMIN_EMAIL` / `VMS_ADMIN_PASSWORD`; the api seeds that account on its first start.

### Backups

Postgres holds users, cameras, events, incidents, cases and reports: back it up daily.

```bash
docker compose --env-file .env.prod -f deploy/compose/docker-compose.yml \
  -f deploy/compose/docker-compose.prod.yml exec -T postgres \
  pg_dump -U "${POSTGRES_USER:-vms}" "${POSTGRES_DB:-vms}" | gzip > "vms-$(date +%F).sql.gz"
```

Copy it off the VM. The `minio_data` (recordings, keyframes, twins, reports) and `qdrant_data`
volumes are bigger and can be archived with the stack stopped
(`docker run --rm -v genai-vms_minio_data:/d -v "$PWD":/b alpine tar czf /b/minio.tgz -C /d .`).
The `caddy_data` volume holds the certificates: losing it only costs a re-issue. A restore has not
been rehearsed.

### Behaviour worth knowing

- Everything the browser needs is on one origin (`/api`, `/webrtc`, `/hls`); only picture and clip
  downloads go to `media.DOMAIN`, which accepts reads only and relies on MinIO's presigned signatures.
- Live video over WebRTC needs `PUBLIC_IP` (the address browsers send media to) and 8189/udp reachable;
  without them the player falls back to HLS.
- Grafana and Prometheus (`obs`) are not behind Caddy: add the profile and reach them through an SSH
  tunnel if wanted.
