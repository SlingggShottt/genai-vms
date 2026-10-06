# Training data for the two adapters

The reasoning service asks two things of a vision model: *where are the stages of this incident*
(TG, `phase_tg` prompt) and *what do these frames of one stage show* (PhaVR, `phase_vr` prompt).
Today the zero-shot base model answers both. These tools prepare, once there are annotations, the
data to fine-tune an adapter for each, and score it against the zero-shot baseline.

| step | what | where | state |
|---|---|---|---|
| annotate | phase spans; captions + VQA answers | `tools/annotation_kit`, `ml/annotation/` (Label Studio) | built, needs people |
| dataset | `phase_labels.jsonl` → TG samples | `ml/training/tg/` (P5-D1) | built, tested on synthetic clips |
| dataset | `phavr_labels.jsonl` → PhaVR samples | `ml/training/phavr/` (P5-J1) | built, tested on synthetic clips |
| train | Unsloth QLoRA on Kaggle (design §8.3) | P5-D2 / P5-J2 | not written |
| evaluate | TG: mIoU, boundary error vs the detector timing and the zero-shot model | `ml/evaluation/reasoning/phase/` (P5-D3) | built; no real result yet |
| evaluate | PhaVR: BLEU-4, METEOR, ROUGE-L, CIDEr, VQA accuracy | P5-J3 | not written |
| serve | `hf_local` provider, PEFT adapter swap | P5-D5 | not written |

Both builders share `dataset_common.py` (splits by source video in one extend-only `splits.json`,
hashing, frame extraction) and render prompts with the reasoning service's own code, so what an
adapter is trained on is what it will be asked. Run the TG builder first and give the PhaVR one the
same `--splits` file. Nothing here has seen a real annotation; `ml/evaluation/results/` has no TG or
PhaVR result because none exists.

Run all of it: `uv run pytest ml/training ml/evaluation` (CI does, in `lint-test-ml-tooling`).
