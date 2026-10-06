# reasoning

Phase-aware event reasoning and incident reports.

| | |
|---|---|
| **Owner** | Divyansh (orchestrator, synthesis); Jatin (evidence, reports, assistant — evidence is built here for now) |
| **Topics** | consumes `vms.correlations.v1`; produces `vms.incidents.v1` (`incidentready.v1`) |
| **Config** | `src/reasoning/settings.py` (`VMS_REASONING_*`), tasks `phase_tg`, `phase_vr`, `incident_synthesis` in `config/models.yaml` |
| **Run** | `uv run --package vms-reasoning python -m reasoning.main` (or `deploy/demo/start.sh`) |

## Pipeline (one job)

```text
job ─▶ events + group ─▶ keyframes from the twins of the window (±15 s)
    ─▶ phase timeline ─▶ evidence per phase × camera ─▶ incident report ─▶ reasoning.incidents
```

1. **Queue.** `reasoning.jobs` is claimed with `FOR UPDATE SKIP LOCKED`; a job whose worker died is
   claimable again when its lease (renewed by every step, 5 min) lapses, and the half-written
   incident it left is marked failed. Jobs come from the api (`POST /events/{id}/analyze`) and
   from `consumers/correlations.py` for closed groups at or above `auto_min_severity` (high),
   capped at `auto_max_per_hour`; one live job per group is enforced by a partial unique index.
2. **Phase timeline** (`steps/phases.py`). Five frames from the primary camera go to `phase_tg`,
   which labels each frame with one of baseline / precursor / escalation / action / aftermath;
   `domain/timeline.py` lifts any backwards label, puts boundaries halfway between frames of
   different phases, and rejects an unusable labelling. Then the timeline comes from the
   detector's own timing and `fallback_used` is set. Today `phase_tg` is the **zero-shot** base
   model — the fine-tuned adapters (P5-D2/P5-J2) are not trained, so expect the fallback often.
3. **Evidence** (`steps/readings.py`). For each phase × camera (≤ 2 cameras) up to two frames of
   that phase go to `phase_vr` with the event type's questions from `config/vqa_bank.yaml`; the
   caption and the answers (matched to the allowed vocabulary, else dropped) become `evidence.v1`
   with stable ids, and the cited frames are copied to `vms-evidence`.
4. **Report** (`steps/synthesis.py`). Two schema-validated calls (stage summaries; causal chain,
   factors, actions) with citation checks and ≤ 2 retries that quote the problems back to the
   model. A claim that still cites nothing valid is **dropped**, never given a borrowed citation,
   and the report says how many were dropped. If nothing cited survives the job fails and the raw
   output is kept on the incident row.

## Daily reports

`reports/facts.py` aggregates a range of site-time days with fixed SQL; `reports/daily.py` asks the
`daily_narrative` task for the summary and accepts it only if every number appears in the figures
(otherwise one retry, then a template text). The worker claims `queued` rows of
`reasoning.daily_reports` and queues yesterday's report itself after `VMS_REASONING_DAILY_REPORT_HOUR`.
`python -m reasoning.reports.daily --date yesterday` queues one by hand.

## Not built

The `hf_local` provider for the LoRA adapters (P5-D5), the synced multi-view playback, server-side PDF
(the UI offers print-to-PDF), `incident.ready` / `job.progress` pushes on the WebSocket (the UI
polls) and similar-incident search.
