# perception

Decode + sample, batched YOLO11 detection, per-camera ByteTrack, attributes, zone membership, SigLIP2 embeddings, digital twin JSON; hosts the grounding endpoint.

| | |
|---|---|
| **Owner** | Divyansh (grounding submodule: Jatin) |
| **Port** | 8030 (internal) |
| **Topics** | consumes vms.segments.v1; produces vms.twin.v1 |
| **Config** | `src/perception/settings.py` via `vms_common.config` (pydantic-settings) — never `os.environ` directly |
| **Metrics** | TBD when implemented — see `docs/design_architecture.md §15` for the `vms_` metrics this service must expose |

Not implemented yet — this is the P1-D1 scaffold. See `docs/backlog.md` for
the story that fills this in, and `docs/style_guide.md §A.1` for the layout
(`domain/` has no I/O and is where unit tests target; `adapters/` wraps DB/S3/
Qdrant/gateway; services never import another service, only `libs/*`).
