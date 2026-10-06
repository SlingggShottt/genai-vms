# TG evaluation (P5-D3)

Scores how well a method places the stages of an incident (baseline → precursor → escalation →
action → aftermath), on the `test.jsonl` of a dataset built by `ml/training/tg/build_dataset.py`.

```bash
# the detector's own timing, and a model through the real gateway (needs Ollama + Redis)
uv run python ml/evaluation/reasoning/phase/evaluate.py \
  --dataset datasets/tg-v1 --split test --methods rules,model \
  --label "zero-shot qwen2.5vl:3b" --out ml/evaluation/results/tg-zero-shot
```

- **`rules`**: no model. The reasoning service's fallback: the flagged span is the action, a lead-in
  before it is escalation then precursor. This is the number a trained adapter has to beat to be
  worth serving.
- **`model`**: the sample's prompt and frames go to the gateway task `phase_tg`; the per-frame
  answer becomes spans with the service's `spans_from_labels`; an unusable answer falls back to the
  rules timeline, as in the service. For the trained adapter, point the `phase_tg` task at it in
  `config/models.yaml` and change `--label`; nothing else differs.

Scores, each a mean over samples with a 95 % bootstrap interval and `n`: **mIoU** (over every stage
the truth or the answer has, in seconds), **boundary error** (seconds, between consecutive true
stages the answer also has; ones it lacks are counted separately), **frame accuracy** (usable
answers only) and the **usable-answer rate**; broken down by event type and by one view versus
several. A test set of a few dozen clips supports little more than these intervals.

## What has been run

Only a plumbing check: 8 synthetic clips (flat colours, one per second, with made-up stage labels)
through the real `qwen2.5vl:3b` gateway on 2026-10-06 — no gateway errors, about 1.8 s per sample,
2 of 8 answers usable. The accuracy figures from that run mean nothing (the frames contain no
incident) and are not recorded. **No real result exists** until phase annotations do (P3-D5's kit
produces them); the baselines in the backlog (zero-shot base and a cloud model on ≤ 40 clips) are
then one command each: the zero-shot one is the `local` profile's `phase_tg`, and a cloud one is the
same command under `VMS_LLM_PROFILE=cloud` with the provider keys set (check that profile's `phase_tg`
entry in `config/models.yaml` first; it has not been exercised here).

## Tests

`uv run pytest ml/evaluation/reasoning` (under a second, no model): hand-checked metrics, both
predictors with a scripted gateway, the fallbacks, and that samples are read exactly as the
builder writes them. CI runs them in `lint-test-ml-tooling`.
