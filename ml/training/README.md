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
| train | QLoRA (design §8.3): `train_adapter.py` (+ `train_adapter_kaggle.ipynb`, never run on Kaggle) | P5-D2 / P5-J2 | TG: trained once on the real 3B on the 4 GB card (2026-10-26, see below); PhaVR: not trained |
| evaluate | TG: mIoU, boundary error vs the detector timing and the zero-shot model | `ml/evaluation/reasoning/phase/` (P5-D3) | first real results, `ml/evaluation/results/tg-adapter-real.md` |
| evaluate | PhaVR: BLEU-4, CIDEr-D, ROUGE-L, METEOR variant, VQA accuracy | `ml/evaluation/reasoning/phavr/` (P5-J3) | built; no real result yet |
| serve | `hf_local` provider, PEFT adapter swap (`libs/vms_common/.../llm/hf_local.py`) | P5-D5 | built; the real 3B base and the TG adapter served and measured |

Both builders share `dataset_common.py` (splits by source video in one extend-only `splits.json`,
hashing, frame extraction) and render prompts with the reasoning service's own code, so what an
adapter is trained on is what it will be asked. Run the TG builder first and give the PhaVR one the
same `--splits` file. The TG path has now seen real clips, with labels of mixed origin (a person's, a
model's drafts, a rule's; each sample says which); there is still no PhaVR result.

Run all of it: `uv run pytest ml/training ml/evaluation` (CI does, in `lint-test-ml-tooling`).

## Training (P5-D2 / P5-J2)

```bash
uv sync --all-packages --extra hf          # peft, bitsandbytes, accelerate
uv run python ml/training/train_adapter.py --dataset datasets/tg-v1 --out adapters/tg-v1 \
    --base Qwen/Qwen2.5-VL-3B-Instruct [--resume] [--upload s3://vms-models/tg/v1]
uv run python ml/training/train_adapter.py --out adapters/tg-v1 --upload-only s3://vms-models/tg/v1
```

One script for both adapters (the dataset's samples carry their own prompt and answer): QLoRA, r 16,
alpha 32, dropout 0.05, LR 2e-4 cosine, 3 epochs, adapters on the language model's linear layers only,
the loss on the answer tokens only (and logits computed for those positions only, which is what keeps
a 152k-token vocabulary from filling a small GPU). It checkpoints every `--save-every` steps and at
each epoch's end; `--resume` restores the optimizer, scaler, position and random state, so an
interrupted run ends with the same adapter as an uninterrupted one. It keeps the lowest-validation-loss
adapter in `best/` (the two files `hf_local` loads), `metrics.jsonl` (every step and epoch) and a
`model_card.md`.

`train_adapter_kaggle.ipynb` runs it on a Kaggle T4: attach the builder's dataset with
`train_adapter.py` copied into it, run the cells, download `best/`, upload with `--upload-only`.

**On a 4 GB card (2026-10-26).** The real 3B model trains on an RTX 3050 with 4 GB with
`--light-prep --optim adamw8bit --dropout 0` (and `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`);
the peak on the longest sample (2,868 tokens, 8 frames of 640×360) is 3.3 GiB of the 3.68 usable. What
it took, in the order the failures came: weights loaded in the dtype autocast runs in (fp16 weights under
bf16 autocast kept a 594 MB converted copy of the tied embedding), 8-bit AdamW (a quarter of the optimizer
state), no LoRA dropout (its copies of the activations), the activations the backward pass keeps moved to
pinned host memory (`save_on_cpu`), and the cache returned after every backward. A run is about 7 s per
sample (more when the machine is short of RAM), roughly 50 minutes for 3 epochs of the 138 TG samples, and
`--resume` continues it. The result of
that run, and what it does not show, is in `ml/evaluation/results/tg-adapter-real.md`.

**What was verified (2026-10-08), and what was not.** On a 10 M-parameter random Qwen2.5-VL built from
the real config and tokenizer and the synthetic TG dataset: the loss falls and token accuracy rises; a
run cut at step 10 and resumed ended with the same metrics (bit for bit) and an adapter within 8e-7 of
the uninterrupted one; the adapter was uploaded to MinIO with its model card, fetched back by
`hf_local` and used for generation (it changes the output; at 24 steps it has not learnt the format).
**Not verified then, and since:** the real 3B model was trained (above); a T4, the notebook on Kaggle, and
whether any adapter beats the zero-shot model on a person's labels are still not (the first answer is
in the results page: not shown). The design names Unsloth; this uses Transformers + PEFT + bitsandbytes, the stack `hf_local`
serves with. `uv run pytest ml/training` runs the unit tests; the tiny end-to-end test needs the Qwen
tokenizer in the Hugging Face cache and is skipped without it (as in CI).
