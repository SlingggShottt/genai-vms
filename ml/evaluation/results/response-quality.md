# Response quality: assistant answers and incident reports

**Run 2026-10-06 19:41 UTC**, local profile. Generator: `qwen2.5:3b` (assistant, reports). Judge: `llama3.2:3b` through the gateway's `eval_judge` task, a different family from the generator. It is a 3B judge, so read its scores as a signal, and the human-agreement figures below as how far to trust it. The judge sees only the records the assistant had: it measures whether an answer follows from them, not whether they are right.

## Assistant answers

| | baseline | after |
|---|---|---|
| questions asked / answered | 72 / 72 | 72 / 72 |
| judged (judge failures) | 71 (1) | 71 (1) |
| judge named a problem | 71 | 71 |
| of those, worded like the prompt's own example | 6 | 4 |
| faithfulness 1–5, raw | 4.648 (4.437–4.831, n=71) | 4.535 (4.296–4.746, n=71) |
| faithfulness 1–5, capped at 3 when a problem was named | 2.901 (2.803–2.972, n=71) | 2.873 (2.775–2.958, n=71) |
| faithfulness 4 or 5, raw | 0.93 | 0.901 |
| relevance 1–5, raw | 4.507 (4.225–4.746, n=71) | 4.394 (4.099–4.648, n=71) |
| relevance 1–5, capped at 3 when a problem was named | 2.831 (2.704–2.93, n=71) | 2.789 (2.648–2.901, n=71) |
| first lookup was the right tool | 0.783 (n=60) | 1.0 (n=60) |
| a lookup used the camera asked about | 0.28 (n=50) | 1.0 (n=50) |
| a lookup used the day asked about | 0.0 (n=42) | 1.0 (n=42) |
| citation precision by the judge, strict / lenient | None / None (n=0) | None / None (n=0) |
| event citations that agree with their sentence (no model) | 26 of 33 consistent, 2 contradicted, 5 unclear | 37 of 53 consistent, 2 contradicted, 14 unclear |
| answers that cite a record | 0.417 | 0.458 |
| tags written that match no record | 27 of 92 | 14 of 80 |
| median seconds per answer | 1.61 | 1.55 |

### How to read this

The rows that need no model (first lookup, camera, day, tags that match no record, event citations that agree with their sentence) are what changed between runs. The judge's scores are not evidence of change or of quality:

- it wrote a problem for **every** answer it judged (71 of 71), including answers whose lookup matched the question, and 4 of them repeat the wording of the prompt's own worked example. So the *capped* rows only say that every answer was capped; they are a floor, not a measure.
- its raw faithfulness went from 4.648 to 4.535 (the intervals overlap), whatever the objective rows did.
- it returned no per-citation judgements, so citation precision *by the judge* is not measured; the model-free agreement check above is what exists (event type and camera against the cited record, whole-sentence, event records only).
- every figure here is about this set of 72 questions on this machine's data, not about the system in general; `human_verification.csv` is how far to trust the judge.

### By category (after)

| category | questions | faithfulness | relevance |
|---|---|---|---|
| count_events | 13 | 4.769 (4.308–5.0, n=13) | 4.769 (4.308–5.0, n=13) |
| count_objects | 8 | 5.0 (5.0–5.0, n=8) | 5.0 (5.0–5.0, n=8) |
| daily_report | 1 | 5.0 (nan–nan, n=1) | 5.0 (nan–nan, n=1) |
| date_specific | 10 | 5.0 (5.0–5.0, n=10) | 5.0 (5.0–5.0, n=10) |
| incidents | 6 | 4.667 (4.333–5.0, n=6) | 4.667 (4.333–5.0, n=6) |
| list_events | 10 | 4.4 (3.5–5.0, n=10) | 4.4 (3.5–5.0, n=10) |
| no_data | 4 | 3.0 (1.5–4.5, n=4) | 3.0 (1.5–4.5, n=4) |
| out_of_scope | 8 | 4.25 (3.25–4.875, n=8) | 3.0 (1.5–4.5, n=8) |
| search | 8 | 4.0 (3.286–4.571, n=7) | 4.0 (3.286–4.571, n=7) |
| timeline | 4 | 4.75 (4.25–5.0, n=4) | 4.75 (4.25–5.0, n=4) |

| expected behaviour | questions | faithfulness | relevance |
|---|---|---|---|
| answer | 60 | 4.678 (4.458–4.847, n=59) | 4.678 (4.458–4.847, n=59) |
| no_data | 4 | 3.0 (1.5–4.5, n=4) | 3.0 (1.5–4.5, n=4) |
| refuse | 8 | 4.25 (3.25–4.875, n=8) | 3.0 (1.5–4.5, n=8) |

## Incident reports

| | baseline | after |
|---|---|---|
| incidents / with a report | 21 / 13 | 21 / 13 |
| validate against `incident.v1` | 13 (1.0) | 13 (1.0) |
| cited ids missing from the report's index | 0 | 0 |
| cited ids missing from the evidence | 0 | 0 |
| statements dropped for citing nothing | 23 | 23 |
| judged | 13 | 13 |
| accuracy 1–5 (judge) | 4.0 (4.0–4.0, n=13) | 4.0 (4.0–4.0, n=13) |
| completeness 1–5 (judge) | 3.923 (3.769–4.0, n=13) | 3.923 (3.769–4.0, n=13) |
| causality 1–5 (judge) | 3.692 (3.462–3.923, n=13) | 3.692 (3.462–3.923, n=13) |
| actionability 1–5 (judge) | 3.615 (3.308–3.846, n=13) | 3.615 (3.308–3.846, n=13) |

## Judge against a person

Not measured yet: `human_verification.csv` (20 % of the answers) and the report rubric form are written next to the run. Once a person has filled them, `summary --filled-sheet ... --filled-rubric ...` adds the agreement and the human rubric means.
