# PhaVR evaluation (P5-J3)

Scores the caption and VQA answers for one stage of one view, on the `test.jsonl` of a dataset built
by `ml/training/phavr/build_dataset.py`.

```bash
uv run python ml/evaluation/reasoning/phavr/evaluate.py \
  --dataset datasets/phavr-v1 --split test --methods template,model \
  --label "zero-shot qwen2.5vl:3b" --out ml/evaluation/results/phavr-zero-shot
```

- **`template`**: no model. A caption made of the event type and the stage, and "Cannot tell" for
  every question. The floor.
- **`model`**: the sample's prompt and frames go to the gateway task `phase_vr`; the answer is parsed
  and cleaned by the service's own `ViewDraft` / `clean_answers`, so what the service would drop
  (an id it did not ask, an answer outside the vocabulary) counts as unanswered. For the trained
  adapter, point `phase_vr` at it in `config/models.yaml` and change `--label`.

Captions: BLEU-4 (corpus), CIDEr-D, ROUGE-L and `meteor_exact` against the one verified caption
(`caption_metrics.py`; the formulas are the usual ones, hand-checked in the tests). `meteor_exact` is
**not** METEOR (that needs WordNet and a stemmer downloaded at run time): it keeps the recall-weighted
mean and the fragmentation penalty but matches identical words only, so compare it between runs of
this harness and with nothing else. VQA: accuracy over the questions asked (unanswered counts as
wrong), plus how often the answer was missing, was "Cannot tell", or claimed an answer the
reference could not give. Means over samples carry 95 % bootstrap intervals; BLEU resamples whole
samples. By stage and by primary versus other view.

A caption metric measures closeness to the verified caption, not truth: a correct caption in other
words scores low. The VQA numbers are the firmer evidence.

## What has been run

A plumbing check on 12 synthetic clips (flat colours) against the real zero-shot `qwen2.5vl:3b`,
2026-10-06. Its accuracy figures mean nothing and are not recorded, **but it found a real bug in the
service**: the model copies the prompt's `[question id]` brackets into its answers, and
`clean_answers` dropped every such answer. In the stored evidence only 7 of 38 views (4 Oct) and 0 of 4
(6 Oct) kept any VQA answer. Fixed in `services/reasoning/steps/readings.py` (ids now ignore brackets,
quotes and backticks) with tests from the recorded answers. Incidents analysed before the fix keep
their empty VQA until they are analysed again. No real PhaVR result exists until there are verified
labels.

## Tests

`uv run pytest ml/evaluation/reasoning/phavr` (a second, no model): hand-checked values for each metric
(a deliberate bug in each metric and in the driver's cleaning, all caught), the template and model predictors with
a scripted gateway, the cleaning, and that samples are read as the builder writes them.
