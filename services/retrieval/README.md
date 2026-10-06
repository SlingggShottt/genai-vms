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

## Also here

- **Knowledge.** The indexer writes each verified event's caption and each incident-report section to
  the `knowledge` collection (dense bge-small + BM25 sparse, `vms_common.qdrant.knowledge`); a text
  search fuses those hits with the visual lists, and `GET /incidents/{id}/similar` searches them.
- **Grounding.** `POST /search/grounding {search_id, result_id}` returns SAM 2.1-tiny masks of the
  objects a result matched, run-length encoded and cached in `vms-masks` (CPU: ~1.3 s cold, ~10 ms
  cached).
- **JIT picture checks** (`jit: true`, reason mode): the rerank's yes/no questions about what the
  records cannot tell go to `jit_vqa` on the result's keyframe; answers are cached per
  `(segment, question)` in `retrieval.jit_cache` and trigger a rescoring pass.
- **Metrics** at `/metrics` (`vms_search_stage_seconds{stage}`, `vms_search_requests_total`,
  `vms_assistant_turns_total`).

Measured on the build machine (`ml/evaluation/results/p7-latency.md`): fast search p50 0.22 s, p95
0.25 s; reason search p50 15.6 s.

## Not built

`candidate.v1` hand-over to a separate JIT worker (JIT runs in-process), crop-from-frame image
queries (`P4-J1` takes uploads only), the retrieval evaluation harness against labelled queries
(`P4-J6`: needs human-labelled ground truth), object masks on the GPU in perception (they run on CPU
here), and tests of the assistant against recorded `FakeGateway` conversations.
