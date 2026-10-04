# retrieval

Reasoning-based search over the archive: text search (`fast` and `reason` modes) and search by image.

| | |
|---|---|
| **Owner** | Divyansh (search); Jatin (image path, grounding, JIT — not built yet) |
| **Port** | 8010, internal — browsers reach it through `services/api` (`POST /api/v1/search`, `/search/image`) |
| **Topics** | none |
| **Config** | `src/retrieval/settings.py` (`VMS_RETRIEVAL_*`), model tasks in `config/models.yaml` |
| **Run** | `uv run --package vms-retrieval python -m retrieval.main` (or `deploy/demo/start.sh`) |

## What a search does

```text
query ─▶ plan ─▶ SigLIP 2 text vectors (CPU) ─▶ Qdrant frames + tracks (+ events by caption)
      ─▶ RRF fusion ─▶ windows of ≤ 10 s per camera ─▶ [reason: reread with the twin] ─▶ response
```

- **Plan** (`domain/plan.py`, `llm_steps.decompose`). `fast` mode uses a vocabulary-only plan
  (categories the detector can emit, colours, zone names, relative times such as "in the last
  hour") so it needs no model. `reason` mode asks the `query_decompose` task for visual
  phrasings and sub-questions, then `finalize_plan` maps categories onto the detector's
  vocabulary and takes times from the text — a 3B model is unreliable at dates. If the model
  cannot answer, the vocabulary plan is used and the response says so in `notes`.
- **Coarse retrieval.** Each visual phrasing is embedded and searched against `frames`
  (whole-scene keyframes) and `tracks` (best crop per object) with camera / time / category
  filters from the plan; matching colours and zones *boost* a track rather than filter it,
  because the colour naming is rough. Verified events whose VLM caption matches the text
  (Postgres full-text on `events.events`) join the fusion as a third list.
- **Windows.** Hits on one camera within `window_s` (10 s) become one result; its score is the sum
  of its hits' RRF scores, normalised to 0–1.
- **Reason.** The top `rerank_top_n` (10) windows are described to the `rerank` task from their
  twin documents (who was there, colours, zones, speed) and any event caption, five per call;
  the model returns a score, a ≤ 60-word trace and `missing[]` questions. The final score is
  `0.4 × fused + 0.6 × model`. Windows the model never saw are capped below the lowest judged one.
  The whole LLM part is bounded by `llm_budget_s`; on timeout the fused order is returned.
- **Image search.** `POST /search/image` embeds the upload with SigLIP 2 vision and searches `tracks`.
- Every search is written to `retrieval.search_logs` (plan, results, per-stage timings).

## Assistant

`POST /assistant/sessions/{id}/messages` streams a turn (`assistant/agent.py`): route or plan → run
tools (`assistant/tools.py`, fixed parameterised SQL and the search pipeline) → stream an answer
that opens with the lookup's own header line → validate the `[E:…]` / `[I:…]` / `[S:…]` tags it
wrote against what the tools handed out (`assistant/evidence.py`). Sessions and the rolling summary
live in `retrieval.chat_*`. See design §10.3 "As built" for why the router and the lead sentence exist.

## Retention

The index outlives recordings: keyframes and segments are removed by the retention policy while
their vectors stay. `VMS_RETRIEVAL_ARCHIVE_SINCE` (ISO time) puts a floor under every search, and
a result whose keyframe no longer exists is dropped and counted in `notes`.

## Not built (backlog)

JIT refinement with the VLM (`P4-J3`, `missing[]` is returned but nothing answers it yet), the
`knowledge` collection (dense + BM25 over event captions — Postgres full-text stands in),
object-level grounding masks (`P4-J2`), crop-from-frame image queries (`P4-J1` takes uploads only),
the evaluation harness (`P4-J6`), and the p95 ≤ 1 s measurement for `fast` mode (a warm search
here takes ~1.5 s, dominated by the CPU text encoder on first use of a phrase).
