# Retrieval benchmark on real labels (MEVA examples)

Scores text search against ground truth nobody had to annotate: the MEVA public *examples* set is
121 short clips of 36 labelled activities (`ex012-open-trunk.mp4`, …). `build_meva_stream.py` joins
them into one stream with a black leader and a 5 s black gap after every clip and writes where each
clip sits on that timeline (`meva_ex_manifest.json`, committed; the video is research-only and
stays under `ml/datasets/raw/`, gitignored). The stream is recorded through the normal pipeline as
camera `meva-ex`; `meva_benchmark.py` then asks 36 plain-language queries (`meva_queries.yaml`) and
checks whether the returned 10 s windows overlap a clip of that activity.

Results of the last run: [`../results/meva-retrieval-benchmark.md`](../results/meva-retrieval-benchmark.md).

## Run it

```bash
# 1. the clips (anonymous HTTPS, no aws CLI needed): examples/videos/ in the public bucket
#    https://mevadata-public-01.s3.amazonaws.com/  -> ml/datasets/raw/meva/examples/videos/   (~0.9 GB)

# 2. join + re-encode (a few minutes, CPU) and register the camera `meva-ex` (disabled)
.venv/bin/python ml/evaluation/retrieval/build_meva_stream.py --register

# 3. record it: perception first, then the simulator, ~37 min, no events service (so no alerts)
MANIFEST=ml/datasets/raw/meva/camera_sim.meva-ex.yaml CAMERA_PREFIX=meva-ex RUN_GATE=0 \
  REPLAY_SECONDS=2200 deploy/demo/refresh.sh

# 4. score it (needs retrieval and, for reason mode, Ollama; footage expires after a day)
uv run --package vms-retrieval python ml/evaluation/retrieval/meva_benchmark.py
```

`--modes fast` skips the language-model rerank (a few seconds in all); `--limit 5` is a smoke test.
Unit tests of the metrics and the timeline alignment (`make test` does not collect `ml/`):
`uv run --package vms-retrieval pytest ml/evaluation/retrieval/tests`.

## How it is scored

- **Relevant window.** A result window is relevant to a query when it overlaps a clip of that
  activity by at least 2 s.
- **Timeline alignment.** Ingestion joins a stream late, so when it began is not known. The
  manifest is slid over the recorded tracks (black frames hold none) and the offset that puts
  tracks inside clips, not inside gaps, wins. The report shows the winning score and the
  runner-up; the harness warns when the margin is under 1.5×.
- **Metrics**, averaged over queries: hit@k (any relevant window in the top k), precision@k, the
  share of the activity's clips reached, and the reciprocal rank of the first relevant window,
  next to the closed-form score of picking windows at random.

## What it does not tell you

It is short staged clips with black gaps, so windows are easy to tell apart; it is a ceiling for
hard footage, not a measure of it. One query per activity, written by the person who built the
benchmark. The queries do not include implicit ones, filters, or several cameras. It says nothing
about answer quality (the assistant) or about the 150-query human-labelled benchmark that
`docs/backlog.md` P4-J6 plans; it is a start toward that, not a replacement.
