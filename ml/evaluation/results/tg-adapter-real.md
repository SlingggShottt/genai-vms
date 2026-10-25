# TG adapter `tg/v1` against zero-shot, on real clips (2026-10-26)

First fine-tuned adapter, trained on the 4 GB card it is served on, scored on the held-out test split
with the same harness and prompt as the zero-shot runs. **Read the last two sections before quoting a
number from this page.**

## What was trained

- Base `Qwen2.5-VL-3B-Instruct`, QLoRA (4-bit NF4), r 16, alpha 32, dropout 0, LR 2e-4 cosine with 5 %
  warm-up, 8-bit AdamW, 3 epochs of 18 optimizer steps (8 samples each), seed 7, loss on the answer
  tokens only. About 50 minutes on an RTX 3050 (4 GB). `ml/training/train_adapter.py --light-prep
  --optim adamw8bit --dropout 0`.
- Data: `~/vms-annotation/tg-real`, built from the 119 labelled clips (59 crime, 60 multi-camera) as
  camera-samples, split by source video: 138 train (83 clips), 26 validation (18 clips), 32 test
  (18 clips). The test split was not used for any decision.
- Validation loss 0.157, 0.115, 0.108 after epochs 1 to 3 (token accuracy 94.7 %, 95.2 %, 96.0 %); the
  last epoch was kept. Training loss ended at 0.084. Uploaded to `s3://vms-models/tg/v1` (with its model
  card) and fetched back by `hf_local` for every run below.

## The 32 test samples

Mean per sample with a 95 % bootstrap interval; the rules row is the detector-timing fallback, which is
built from the labelled action span and is **not independent** evidence (it is shown because the adapter
has to beat it to be worth serving).

| run | frames as seen | mIoU | boundary error | frame accuracy | usable answers | s/sample |
|---|---|---|---|---|---|---|
| rules (no model) | – | 0.537 (0.462–0.617) | 0.7 s (0.56–0.85) | 0.801 (0.759–0.842) | – | – |
| zero-shot, Ollama `qwen2.5vl:3b` | long edge 360, 16k context (run of 10-24) | 0.322 (0.238–0.408) | 4.83 s (3.44–6.31) | 0.405 (0.322–0.484) | 0.688 | 18.5 |
| zero-shot, `hf_local` base | long edge 360 | 0.335 (0.258–0.421) | 4.76 s (3.49–6.12) | 0.471 (0.405–0.536) | 0.781 | 2.3 |
| **adapter** `tg/v1` | long edge 360 | 0.390 (0.318–0.469) | 2.42 s (1.62–3.47) | 0.656 (0.587–0.728) | 1.000 | 3.1 |
| zero-shot, `hf_local` base | as trained (640×360) | 0.274 (0.229–0.318) | 3.85 s (2.45–5.31) | 0.468 (0.407–0.526) | 0.719 | 3.5 |
| **adapter** `tg/v1` | as trained (640×360) | 0.354 (0.284–0.425) | 2.79 s (1.90–3.92) | 0.610 (0.537–0.683) | 1.000 | 4.7 |

The first `hf_local` pair was run with the registry's `max_image_edge: 360`, which shrinks a 640×360
frame to 360×202; the adapter was trained on 640×360 frames (the dataset builder caps the height, not
the long edge). That was noticed after the first pair, so the second pair uses the size it was trained
on. Both are reported; the second is the like-for-like one.

## Paired difference, adapter minus zero-shot, by who made the label

Per-clip mIoU of both runs on the same clips (`ml/evaluation/reasoning/phase/compare.py`), so the
interval is the interval of the difference.

| labels made by | n | zero-shot | adapter | difference (95 % interval) | adapter better / tied / worse |
|---|---:|---:|---:|---|---|
| **all clips** | 32 | 0.274 | 0.354 | **+0.080 (+0.005 to +0.153)** | 20 / 3 / 9 |
| a person (from scratch, or a draft accepted or corrected) | 6 | 0.237 | 0.196 | −0.040 (−0.236 to +0.103) | 3 / 1 / 2 |
| a model draft that looked at the clip | 17 | 0.278 | 0.300 | +0.021 (−0.062 to +0.101) | 8 / 2 / 7 |
| a model draft by the padding rule (nothing could be picked out) | 8 | 0.291 | 0.556 | **+0.265 (+0.158 to +0.400)** | 8 / 0 / 0 |
| the dataset's crime span | 1 | 0.286 | 0.620 | +0.334 | 1 / 0 / 0 |

(The 360-edge pair gives the same picture: overall +0.054, −0.054 to +0.163; padding rule +0.291;
people −0.022; drafts that looked −0.047. `tg-adapter-vs-hf-base.md`.)

## What this does and does not show

- **It shows** that a 3B vision model can be QLoRA-trained on a 4 GB card and served from the same
  card: the adapter always answers in the required form (32 of 32 usable against 23 of 32 for the same
  base), puts its boundaries one to two seconds nearer the labelled ones (not a clean win: the intervals
  touch), and labels more frames correctly (0.61 against 0.47, intervals apart).
- **It does not show** that the adapter sees the stages in the video better. Its overall mIoU gain is
  carried entirely by the clips whose labels came from the padding rule: it learned the rule (the
  prompt carries the flagged span, and those labels are that span plus a fixed margin) and reproduces
  it on clips of the same kind. On the labels a person or a model looking at the clip made, there is no
  gain that the data can tell from zero (the intervals include zero, the point estimates go both ways),
  and 6 clips of a person's judgement is too few to say more.
- **It does not beat the detector-timing fallback** on those judged labels (0.196 against 0.564 on a
  person's, 0.300 against 0.612 on drafts that looked), and it hardly ever says `precursor` or
  `escalation` (6 stage mentions in 32 answers; the labels have 21): it falls back to
  baseline, action, aftermath. The rules row has the flagged span handed to it, so this is not a fair
  race, but it does mean that **serving this adapter in place of the rules timeline is not justified by
  this result**. The service's chain (adapter, then zero-shot base, then rules) is unchanged.
- The headline claim of the design, "the fine-tuned adapter beats zero-shot", is therefore supported
  only as "it is a better-formed and rule-faithful zero-shot", not as better understanding of the
  incident's phases.

## Why the labels limit this, and what would change it

- Of the 119 labelled clips, a person's own marks cover 9 from scratch and 20 drafts accepted or
  corrected; 58 are model drafts from contact sheets, 25 a padding rule, 7 the dataset's crime span
  (`ml/annotation/labels/README.md`). A model trained on its own kind of drafts, and scored on them,
  mostly learns the drafts.
- The test split is 32 camera-samples from 18 clips on 8 cameras, and 24 of the 32 are everyday MEVA
  activity, 8 are crime clips. Samples of one clip (its 2 or 3 camera views) are not independent, which
  the bootstrap ignores, so every interval above is tighter than it should be. MEVA clips of one scene
  share cameras and backgrounds, so train and test are also not as far apart as the split by source
  video suggests.
- One training run, one seed, no hyperparameter search; the intervals do not include the variation
  between runs.
- What would change the conclusion: more clips marked by a person (the 15 they have done is the
  reliable core), retrained and scored on a test set made only of those, with the padding-rule clips
  left out of training or at least out of the test.

## Cost of serving (P5-D5), measured on the same card

Through the gateway's `hf_local` path with the adapter active, on the six test samples with the most
frames, after one warm-up call; `torch.cuda.max_memory_allocated` after the warm-up.

| frames as seen | prompt tokens (8 frames) | peak allocated | peak reserved | warm call | first call (model load) |
|---|---:|---:|---:|---:|---:|
| long edge 360 | 1,170 to 1,480 | 2,712 MiB | 2,888 MiB | 3.5 s median, 4.1 s max | 19 s |
| as trained, 640×360 | 2,210 to 2,835 | 2,994 MiB | 3,248 MiB | 5.7 s median, 5.8 s max | 22 s |

The card has 3.68 GiB usable. For comparison, training peaked at 3.3 GiB (below).

## Fitting the training on 4 GB

The first attempts ran out of memory (in the output layer, then in the backward pass). What made it
fit, each measured on the longest sample (2,868 tokens): weights loaded in the dtype autocast runs in
(a mismatch kept a 594 MB converted copy of the tied embedding), 8-bit AdamW, LoRA dropout 0, the
activations kept for the backward pass held in pinned host memory, and the cache returned after each
backward. Peak 3,315 MiB with two samples accumulating. Details in `ml/training/README.md`.

Files: `tg-hf640-base.md`, `tg-hf640-adapter.md` (+ `-reading.md`), `tg-hf-base.md`, `tg-hf-adapter.md`,
`tg-ollama-test.md`, `tg-adapter-vs-hf640-base.md`, `tg-adapter-vs-hf-base.md`,
`tg-adapter-vs-ollama.md`; the `.json` beside each `.md` holds the summary numbers, `tg-hf*-answers.jsonl`
are the model answers they were computed from, `tg-v1-training-metrics.jsonl` and `tg-v1-model-card.md` are
the training record. (The dataset itself, `tg-real`, is built from the labels in `ml/annotation/labels/` and
the clips, which are not in the repository.)
