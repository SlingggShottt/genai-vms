# Demo runbook

The things to show: **reasoning-based search**, **event reasoning** (phase-aware analysis of an
event), **automated incident summarisation**, the **assistant** and **daily reports**.

## Bring it up

```bash
make up PROFILE=infra,core            # Kafka, Postgres, Qdrant, MinIO, Redis, MediaMTX, ingestion, indexer, events, correlation
make migrate                          # needs migrations 0009-0011 (reasoning, retrieval, chat, daily reports)
VMS_RETRIEVAL_ARCHIVE_SINCE=<today>T00:00:00Z deploy/demo/start.sh   # Ollama, retrieval :8010, reasoning, api :8000, UI :5173
```

Log in at http://127.0.0.1:5173 with the admin account from `.env`. Stop the host services with
`deploy/demo/stop.sh`. Logs are in `.demo/logs/`.

`VMS_RETRIEVAL_ARCHIVE_SINCE` hides footage whose recordings the retention policy has already
removed (older keyframes would be broken pictures). Leave it unset on a fresh archive.

## Footage

The pipeline needs recent footage: `make up PROFILE=infra,core,tools` starts the camera simulator
(`docker stop vms-camera-sim` when done; it writes 2-3 GB/h) and perception runs on the host
(`uv run --package vms-perception python -m perception.main`). On the 4 GB GPU, **stop perception
(and the camera simulator) before demoing**: perception, the events gate and the language model
cannot share the card, and Ollama silently falls back to the CPU when perception holds the VRAM
(`curl localhost:11434/api/ps` shows `size_vram`; if it is tiny, `curl -XPOST
localhost:11434/api/generate -d '{"model":"qwen2.5vl:3b","keep_alive":0}'` and it reloads onto the
GPU).

## What to show

1. **Search** (`/search`). Try *a person in a red top near the service door*; compare **Fast** (about a
   second, visual similarity only) with **Reason** (about a minute on this GPU: a model rereads the
   best windows against the system's records and each card shows why it ranked). Try *Search by
   image* with a crop. *Open in playback* jumps to the recording at that time.
2. **Event reasoning** (`/events` → open an event → *Reasoning* → *Analyse incident*). Progress and the
   queue position are shown while it runs (a few minutes locally).
3. **Incident report** (`/incidents`). Phase band, what each phase showed (captions and Q&A from the
   VQA bank), causal chain with evidence chips (press one to see the frame or answer behind it), the
   limitations, and the provenance line — which says honestly when the phase boundaries came from the
   detector's timing instead of the model.
4. **Automation.** Closed correlation groups of severity high or above are analysed without a click
   (at most 6 an hour); they appear in `/incidents` as *Writing report* and then finish.

5. **Assistant** (`/assistant`). Start from a suggested question, e.g. *Were there any serious incidents
   on cam01 today?* — the lookup runs first and what it found is listed under the answer; every chip
   opens the event, report or recording behind it. A tag the model invents is dropped, not shown.
6. **Daily reports** (`/reports`). *Generate report*, pick a day; it fills in within a minute. The
   summary is written by the model but every number in it is checked against the figures (the page
   says when it fell back to the standard summary). *Print or save as PDF*.

7. **Object outlines.** Search results outline the person or object that matched (SAM 2.1-tiny, on the CPU;
   the first outline of a frame takes about a second). *Look closer* (reason mode) makes a vision model
   check what the records could not tell, in the picture itself — several minutes on this GPU.
8. **Timeline and cases** (`/timeline`, `/cases`). Drag across a camera's lane to pick a period, zoom to it,
   open the recording or *Save to case*; press a marker to see the event or report. *Save to case* is also on
   search results, events and incident reports. A report page lists *Similar incidents*.
9. **Dashboards.** `make up PROFILE=infra,obs` adds Prometheus (:9090) and Grafana (:3000, `admin` /
   `GRAFANA_ADMIN_PASSWORD`, default `admin`); the "GenAI-VMS overview" dashboard is provisioned.

## Known limits (say them before they are found)

- Phase location and captions use the **zero-shot** Qwen2.5-VL-3B: the fine-tuned adapters are not
  trained. Expect generic wording and frequent use of the detector-timing fallback.
- The demo clip loops, so many results look alike; there is one real camera (`cam01`), so nothing
  is correlated across cameras here.
- No cloud keys are set, so everything runs on the local 4 GB GPU. Ollama swaps between the vision and the text model when activity moves between them (about 20 s); the first search or question after a pause pays for it.
