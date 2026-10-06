# PhaVR dataset builder (P5-J1)

Turns the phase captions and VQA answers a person verified (`phavr_labels.jsonl`, `phavr_label.v1`,
from the annotation kit) into instruction data for the PhaVR adapter. No GPU, no network; training
(P5-J2) is on Kaggle.

```bash
uv run python ml/training/phavr/build_dataset.py \
  --labels phavr_labels.jsonl --phase-labels phase_labels.jsonl \
  --videos-root /path/to/vms-evidence --out datasets/phavr-v1 \
  --splits datasets/tg-v1/splits.json            # the TG builder's file: same videos, same splits
```

Output (relative to `--out`): `train|val|test.jsonl` (one chat-format sample per labelled phase of
one clip in one view), `frames/<clip>/<view>/<phase>/NN.jpg` (≤ 360 px high), `manifest.json`
(config, prompt and VQA-bank hashes, splits, counts, a hash of every file), `dataset-metadata.json`
for Kaggle.

## What a sample is

2–4 frames from inside the phase (the service shows `frames_per_view`, default 2, at most 4), picked
with the service's `pick_evenly`; the user turn is the `phase_vr` 1.0 prompt rendered as
`services/reasoning/steps/readings.py` renders it (stage meaning, event type, the bank's questions,
times on the clip's clock); the assistant turn is `{"caption": "...", "answers": [{"id", "answer"}]}`,
the shape the service parses (`ViewDraft`) with each answer in the bank's own spelling. A test runs
the service's real `read_view` with a recording gateway and requires the identical prompt, and runs
the answer through the service's own `clean_answers`.

## Choices

- **A question is asked only if the label answers it**, so the model is never taught to answer
  something nobody checked. `bank_questions_without_an_answer` in the manifest counts the rest.
- **Skipped, not guessed:** an empty caption, an answer outside the question's vocabulary ("Probably"),
  a view the phase labels do not have, a missing video. Each is listed in `manifest.json` →
  `skipped`; nothing is repaired.
- **Splits** are by source video, 70/15/15, in the shared `splits.json` (extend-only; a video missing
  from this run keeps its split, so the two builders cannot disturb each other).
- A stage too short to hold a frame gets the frame nearest its middle, as in the service.
- Each sample also carries `edits` (how far a person moved the model's draft), so a label that is just
  the draft can be weighed or dropped later; the builder does not filter on it.

## Tests and limits

`uv run pytest ml/training/phavr` (about 15 s, synthetic one-colour-per-second videos; ten tests, a
surviving bug in the split-sharing test was found by mutation and fixed). CI: `lint-test-ml-tooling`.
It has only ever run on synthetic labels. Not built: the training notebook (P5-J2), the evaluation
(P5-J3), serving (P5-D5).
