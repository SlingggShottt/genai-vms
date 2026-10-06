# TG dataset builder (P5-D1)

Turns phase-annotated clips (`phase_labels.jsonl`, `phase_labels.v1`, from the annotation kit)
into instruction data for the temporal-grounding adapter. Nothing here needs a GPU or a network;
training itself (P5-D2) happens on Kaggle.

```bash
uv run python ml/training/tg/build_dataset.py \
  --labels phase_labels.jsonl \
  --videos-root /path/to/vms-evidence \      # s3://vms-evidence/clips/x/cam.mp4 -> <root>/clips/x/cam.mp4
  --out datasets/tg-v1
```

What it writes under `--out`: `train.jsonl`, `val.jsonl`, `test.jsonl` (one chat-format sample per
clip and camera), `frames/<clip>/<camera>/NN.jpg` (at most 360 px high), `manifest.json` (config,
prompt hash, split assignment, counts, a hash of every file), `splits.json` and
`dataset-metadata.json` for `kaggle datasets create` (put your username in `id` first).

## What a sample is

For one camera view of one clip: 5–8 frames (a seeded count per sample, the range the service can
show), picked from the clip's one-frame-a-second timeline with the service's own `pick_evenly`; the
user turn is the `phase_tg` 1.0 prompt rendered the way `services/reasoning/steps/phases.py`
renders it; the assistant turn is `{"phases": ["baseline", "baseline", "action", ...]}`, one stage
per frame, the shape the service parses (`FrameLabels`). So a trained adapter is a drop-in
replacement for the zero-shot model. A unit test runs the service's real `locate_phases` with a
recording gateway and requires the training prompt to be identical to the one it sent.

The design (§8.3) describes span-style answers; the service does not parse those today, and a
model taught a format the service cannot read would be useless, so the per-frame form is trained.
If the service moves to spans, change `sample_record` and the prompt together.

## Choices you may want to change

- **The flagged span in the prompt.** The service shows the detector's span ("the flagged incident
  runs from X s to Y s"). The labels do not have one, so it is the annotated `action` phase moved by
  up to `--jitter` s (1.5) at each end, seeded per sample, because the detector's timing is rarely
  exact. Without jitter the model could learn to copy the span.
- **A frame outside every annotated span** takes the stage before it (or the first stage, if it is
  before all of them), so labels never go backwards. `manifest.json` counts these
  (`frames_outside_every_span`); a large number means the annotation leaves gaps.
- **Splits are by source video** (70/15/15, at least one video each in val and test from three
  videos up) and recorded in `splits.json`, which is only ever extended: add annotations and rebuild
  and no earlier video moves between splits. Point the PhaVR builder (P5-J1) at the same file.
- **Clips with fewer than 3 frames** and videos that cannot be found are skipped and listed in the
  manifest (`skipped`), not fatal; if nothing can be built, it fails and says why.

## Tests

`uv run pytest ml/training/tg/tests` (about 15 s: they encode small synthetic videos with one flat
colour per second, so "the frame shown at t s is the frame at t s" is checked by colour). CI runs
them in `lint-test-ml-tooling`.

## Not done here

The training notebook (P5-D2), evaluation (P5-D3), adapter serving (P5-D5), the multi-view sample
variant (all views of a clip in one prompt, which the service does not send yet) and any real
data: there are no phase annotations yet, so this has only ever run on synthetic clips.
