# Response-quality evaluation (P7-J4)

Scores what the assistant says (72 questions) and what incident reports say (all incidents with a
report), against the records behind them. Results: `ml/evaluation/results/response-quality.md`.

```bash
# needs the host stack: deploy/demo/start.sh (api, retrieval, Ollama) and the Docker infra
RQ=ml/evaluation/response_quality
uv run python $RQ/run.py collect --run $RQ/runs/<name>            # ask the 72 questions through the api
uv run python $RQ/run.py judge   --run $RQ/runs/<name> [--resume] # judge answers + incident reports
uv run python $RQ/run.py summary --run $RQ/runs/<name> --compare $RQ/runs/<earlier>
```

`collect` waits out the api's 20-per-minute limit (`Retry-After`). `judge` writes each row as it
finishes; if it is interrupted, `--resume` keeps the rows already judged and only redoes the rest
(use it only with the same judge and the same transcripts, otherwise the run mixes two judges).
`summary` recomputes the checks that need no model, so a better check applies to an old run without
judging it again.

## What is measured, and what to believe

| Signal | How | Trust |
|---|---|---|
| first lookup was the right tool; a lookup used the camera / the day the question names | compares the question's known camera, day and tool with the lookups the assistant actually made | model-free: the evidence of change |
| tags written that match no record; event citations that agree with their sentence | the answer's `[E:xxxxxxxx]` tags against the records it cited, by event type and camera (whole sentence, event records only) | model-free |
| report validates against `incident.v1`; cited ids exist | `IncidentReportV1` validation; ids against the report's index and evidence bundle | model-free |
| faithfulness / relevance (answers), accuracy / completeness / causality / actionability (reports) | a judge through the gateway task `eval_judge` (`llama3.2:3b`, a different family from the generator) | **weak**: see the results file |
| judge agreement with a person | `human_verification.csv` (a blind 20 % sample) and `report_rubric_form.csv`, filled by a person, then `summary --filled-sheet … --filled-rubric …` (quadratic-weighted kappa) | the only way to know how far to trust the judge |

Measured limits of the 3B judge on this machine: it names a problem for every answer, repeats the
wording of its own prompt's worked example in some, returns no per-citation judgements, and gave the
two runs the same scores while the objective checks moved. Do not quote its scores as quality.

## Files

`questions.py` (the question set, seeded from the data), `collect.py` (the api client), `judge.py`
(prompts, scope and citation checks, report checks), `aggregate.py` (numbers, human sheets, kappa),
`run.py` (the CLI and the results page), `tests/`. The judge prompt is
`libs/vms_common/src/vms_common/llm/prompts/eval_judge/1.0.md`. `runs/<name>/` holds one run's
questions, transcripts, judgements and sheets.

Tests: `uv run pytest ml/evaluation/response_quality` (no network, no model: `FakeGateway`).

Memory: Ollama's runner uses 6 GB or more on the CPU when perception holds the GPU. Start the host
services with `deploy/demo/start.sh`, which puts each in its own systemd scope so an out-of-memory
kill cannot take the editor down with it.
