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

## PDF reports

Once an incident report is `generated`, or a daily report `ready`, the worker renders its PDF
(`reports/pdf.py`: Jinja2 templates in `reports/templates/` -> HTML -> WeasyPrint; A4, light theme,
header with the site and period, footer with the profile, time and page numbers, evidence frames in a
two-column grid, severity as a shape and a word) and stores it at `s3://vms-reports/incidents/<id>.pdf`
or `.../daily/<id>.pdf`, noting the address in `pdf_uri` (migration 0014). The api hands out a link
that works for 15 minutes (`GET /incidents/{id}/pdf`, `GET /reports/daily/{id}/pdf`; `has_pdf` on the
summaries) and the pages have a *Download PDF* button. A PDF that cannot be made (a missing system
library, a frame that is gone) is logged and leaves a report without one; it never fails the report.
`VMS_REASONING_PDF_ENABLED=false` switches it off; `VMS_REASONING_SITE_NAME` is the name in the page
header. For reports made before this existed: `python -m reasoning.reports.backfill`.

The image installs Pango and DejaVu fonts (see the Dockerfile); Barlow and Source Serif 4, which
the style guide names, are used where installed and otherwise fall back to DejaVu. Not done: the daily
PDF is not indexed into the `knowledge` collection.

## Not built

`incident.ready` / `job.progress` pushes on the WebSocket (the UI polls). (The `hf_local` provider is
built: `libs/vms_common/.../llm/hf_local.py`; the synced multi-view playback is in the frontend.)
