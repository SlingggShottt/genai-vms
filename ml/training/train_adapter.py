"""QLoRA fine-tuning of one adapter (TG or PhaVR) on a dataset built by `ml/training/{tg,phavr}`.

    uv run python ml/training/train_adapter.py \\
        --dataset datasets/tg-v1 --out adapters/tg-v1 \\
        --base Qwen/Qwen2.5-VL-3B-Instruct [--upload s3://vms-models/tg/v1]

The same script trains both adapters (the dataset's samples carry their own prompt and answer), with
the design's hyperparameters (§8.3): QLoRA, 4-bit NF4, r = 16, alpha = 32, dropout 0.05, LR 2e-4
cosine, 3 epochs. Only the language model's linear layers get adapters, not the vision tower. The
loss is on the assistant's answer only.

Built to survive a Kaggle session: every `--save-every` optimizer steps and at each epoch's end it
writes `<out>/checkpoint/` (the adapter and the optimizer, scheduler, position in the epoch and RNG
state), and `--resume` carries on from it; the data order of an epoch depends only on `--seed` and
the epoch number. Per epoch it measures validation loss and answer-token accuracy and keeps the
adapter with the lowest validation loss in `<out>/best/` (exactly the two files `hf_local` loads),
with a `model_card.md`. `metrics.jsonl` has every step and epoch for plotting.

What this does NOT do: the design names Unsloth; this uses Transformers + PEFT + bitsandbytes, the
stack `hf_local` serves with and the one that could be tested without a Kaggle GPU. Mixed
precision is bf16 where the card has it, fp16 with a gradient scaler where not (a T4). Scoring
the adapter (mIoU, BLEU...) is `ml/evaluation/reasoning/*`, which asks the gateway.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

IGNORE = -100
# Language-model linears only: the vision tower has projection layers with the same names.
TARGET_MODULES = r"^(?!.*visual).*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)$"
ADAPTER_FILES = ("adapter_config.json", "adapter_model.safetensors")


@dataclass
class TrainConfig:
    dataset: Path
    out: Path
    base: str = "Qwen/Qwen2.5-VL-3B-Instruct"
    epochs: int = 3
    lr: float = 2e-4
    rank: int = 16
    alpha: int = 32
    dropout: float = 0.05
    grad_accum: int = 8
    warmup_ratio: float = 0.05
    weight_decay: float = 0.0
    max_grad_norm: float = 1.0
    seed: int = 7
    load_4bit: bool = True
    grad_checkpointing: bool = True
    save_every: int = 50  # optimizer steps
    max_steps: int | None = None  # stop after this many optimizer steps (a smoke test)
    resume: bool = False


# ---- pure pieces ---------------------------------------------------------------------------


def lr_at(step: int, total: int, *, base_lr: float, warmup_ratio: float) -> float:
    """Linear warm-up, then cosine to zero. `step` counts optimizer steps from 0."""
    warmup = max(1, round(total * warmup_ratio))
    if step < warmup:
        return base_lr * (step + 1) / warmup
    progress = (step - warmup) / max(1, total - warmup)
    return base_lr * 0.5 * (1 + math.cos(math.pi * min(1.0, progress)))


def epoch_order(n: int, epoch: int, seed: int) -> list[int]:
    """The order samples are visited in one epoch: a function of the seed and the epoch only, so a
    resumed run sees exactly the data an uninterrupted one would."""
    order = list(range(n))
    random.Random(seed * 100_003 + epoch).shuffle(order)  # noqa: S311 - a shuffle, not security
    return order


def labels_for(ids: list[int], prompt_len: int) -> list[int]:
    """The training targets: the answer's tokens, nothing of the prompt (frames and question)."""
    return [IGNORE] * prompt_len + ids[prompt_len:]


def steps_per_epoch(n_samples: int, grad_accum: int) -> int:
    return math.ceil(n_samples / grad_accum)


def read_split(root: Path, name: str) -> list[dict[str, Any]]:
    path = root / f"{name}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def template_messages(sample: dict[str, Any]) -> list[dict[str, Any]]:
    """The dataset's messages with each `{"type": "image", "image": path}` reduced to a bare
    placeholder, which is what the processor's chat template expects (the pictures go in beside)."""
    out = []
    for message in sample["messages"]:
        content = message["content"]
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        out.append(
            {
                "role": message["role"],
                "content": [
                    {"type": "image"}
                    if p["type"] == "image"
                    else {"type": "text", "text": p["text"]}
                    for p in content
                ],
            }
        )
    return out


def build_example(sample: dict[str, Any], root: Path, processor: Any) -> dict[str, Any]:
    """Tensors for one sample: input ids with the prompt masked out of the labels."""
    from PIL import Image  # noqa: PLC0415

    pictures = []
    for rel in sample["images"]:
        with Image.open(root / rel) as image:
            pictures.append(image.convert("RGB"))
    messages = template_messages(sample)
    full_text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    prompt_text = processor.apply_chat_template(
        messages[:-1], tokenize=False, add_generation_prompt=True
    )
    full = processor(text=[full_text], images=pictures or None, return_tensors="pt")
    prompt = processor(text=[prompt_text], images=pictures or None, return_tensors="pt")
    ids = full["input_ids"][0].tolist()
    full["labels"] = _tensor([labels_for(ids, prompt["input_ids"].shape[1])])
    return dict(full)


def _tensor(rows: list[list[int]]) -> Any:
    import torch  # noqa: PLC0415

    return torch.tensor(rows, dtype=torch.long)


# ---- the run -------------------------------------------------------------------------------


def pick_precision() -> tuple[Any, bool]:
    """(autocast dtype, whether a gradient scaler is needed): bf16 where the card has it."""
    import torch  # noqa: PLC0415

    if not torch.cuda.is_available():
        return torch.float32, False
    if torch.cuda.is_bf16_supported():
        return torch.bfloat16, False
    return torch.float16, True


def load_model(cfg: TrainConfig) -> tuple[Any, Any]:
    import torch  # noqa: PLC0415
    from transformers import AutoModelForImageTextToText, AutoProcessor  # noqa: PLC0415

    kwargs: dict[str, Any] = {
        "dtype": torch.float16 if torch.cuda.is_available() else torch.float32
    }
    if torch.cuda.is_available():
        kwargs["device_map"] = {"": 0}
    if cfg.load_4bit:
        from transformers import BitsAndBytesConfig  # noqa: PLC0415

        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
        )
    model = AutoModelForImageTextToText.from_pretrained(cfg.base, **kwargs)
    return model, AutoProcessor.from_pretrained(cfg.base)


def answer_loss(model: Any, batch: dict[str, Any], amp: Any) -> tuple[Any, int, int]:
    """(loss, answer tokens, correct tokens) for one sample. The answer is the last tokens of the
    sequence, so the model is asked for the logits of those positions only: a vocabulary of 152k
    times a prompt of 1,500 tokens is gigabytes of logits that nothing needs."""
    import torch  # noqa: PLC0415
    from torch.nn.functional import cross_entropy  # noqa: PLC0415

    labels = batch["labels"][0]
    n = int((labels != IGNORE).sum())
    inputs = {k: v for k, v in batch.items() if k != "labels"}
    with torch.autocast(labels.device.type, dtype=amp, enabled=labels.device.type == "cuda"):
        out = model(**inputs, logits_to_keep=n + 1)
    logits = out.logits[0, :-1].float()  # the position before each answer token predicts it
    target = labels[-n:]
    loss = cross_entropy(logits, target)
    return loss, n, int((logits.argmax(-1) == target).sum())


def evaluate(model: Any, examples: list[dict[str, Any]], device: Any, amp: Any) -> dict[str, float]:
    """Mean loss and answer-token accuracy over `examples` (the answer's tokens only)."""
    import torch  # noqa: PLC0415

    model.eval()
    loss_sum = tokens = correct = 0.0
    with torch.no_grad():
        for example in examples:
            batch = {k: v.to(device) for k, v in example.items()}
            loss, n, right = answer_loss(model, batch, amp)
            loss_sum += float(loss) * n
            tokens += n
            correct += right
    model.train()
    return {"loss": loss_sum / max(tokens, 1), "token_accuracy": correct / max(tokens, 1)}


def copy_adapter(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for name in ADAPTER_FILES:
        shutil.copy2(src / name, dst / name)


def train(cfg: TrainConfig) -> dict[str, Any]:
    import torch  # noqa: PLC0415
    from peft import (  # noqa: PLC0415
        LoraConfig,
        PeftModel,
        get_peft_model,
        prepare_model_for_kbit_training,
    )

    random.seed(cfg.seed)
    torch.manual_seed(cfg.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    amp, scaled = pick_precision()
    cfg.out.mkdir(parents=True, exist_ok=True)
    ckpt = cfg.out / "checkpoint"

    model, processor = load_model(cfg)
    if cfg.load_4bit:
        model = prepare_model_for_kbit_training(
            model, use_gradient_checkpointing=cfg.grad_checkpointing
        )
    elif cfg.grad_checkpointing:
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()
    resuming = cfg.resume and (ckpt / "state.pt").exists()
    if resuming:
        model = PeftModel.from_pretrained(model, str(ckpt / "adapter"), is_trainable=True)
    else:
        lora = LoraConfig(
            r=cfg.rank, lora_alpha=cfg.alpha, lora_dropout=cfg.dropout,
            target_modules=TARGET_MODULES, task_type="CAUSAL_LM",
        )  # fmt: skip
        model = get_peft_model(model, lora)
    for param in model.parameters():
        if param.requires_grad:
            param.data = param.data.float()  # LoRA weights train in fp32
    model.train()

    train_rows = read_split(cfg.dataset, "train")
    if not train_rows:
        raise SystemExit(f"{cfg.dataset}/train.jsonl has no samples")
    examples = [build_example(r, cfg.dataset, processor) for r in train_rows]
    val = [build_example(r, cfg.dataset, processor) for r in read_split(cfg.dataset, "val")]

    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=cfg.lr, weight_decay=cfg.weight_decay)
    scaler = torch.amp.GradScaler("cuda", enabled=scaled)
    per_epoch = steps_per_epoch(len(examples), cfg.grad_accum)
    total = per_epoch * cfg.epochs

    step, epoch, pos, best = 0, 0, 0, float("inf")
    if resuming:
        state = torch.load(ckpt / "state.pt", map_location="cpu", weights_only=False)
        optimizer.load_state_dict(state["optimizer"])
        scaler.load_state_dict(state["scaler"])
        torch.set_rng_state(state["rng_cpu"])
        if torch.cuda.is_available() and state.get("rng_cuda") is not None:
            torch.cuda.set_rng_state(state["rng_cuda"])
        step, epoch, pos, best = state["step"], state["epoch"], state["pos"], state["best"]
        print(f"resumed at step {step} (epoch {epoch + 1}, sample {pos})", flush=True)

    metrics = (cfg.out / "metrics.jsonl").open("a")

    def log(row: dict[str, Any]) -> None:
        metrics.write(json.dumps(row) + "\n")
        metrics.flush()
        print(json.dumps(row), flush=True)

    def save(at_epoch: int, at_pos: int) -> None:
        ckpt.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(str(ckpt / "adapter"))
        torch.save(
            {
                "optimizer": optimizer.state_dict(), "scaler": scaler.state_dict(),
                "step": step, "epoch": at_epoch, "pos": at_pos, "best": best,
                "rng_cpu": torch.get_rng_state(),
                "rng_cuda": torch.cuda.get_rng_state() if torch.cuda.is_available() else None,
            },
            ckpt / "state.pt",
        )  # fmt: skip

    stopped = False
    started = time.time()
    while epoch < cfg.epochs and not stopped:
        order = epoch_order(len(examples), epoch, cfg.seed)
        losses: list[float] = []
        accumulated = 0
        for index in range(pos, len(order)):
            batch = {k: v.to(device) for k, v in examples[order[index]].items()}
            loss, _, _ = answer_loss(model, batch, amp)
            losses.append(float(loss))
            scaler.scale(loss / cfg.grad_accum).backward()
            accumulated += 1
            last = index == len(order) - 1
            if accumulated == cfg.grad_accum or last:
                for group in optimizer.param_groups:
                    group["lr"] = lr_at(step, total, base_lr=cfg.lr, warmup_ratio=cfg.warmup_ratio)
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(params, cfg.max_grad_norm)
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad(set_to_none=True)
                step += 1
                accumulated = 0
                recent = losses[-cfg.grad_accum :]
                log(
                    {
                        "kind": "step",
                        "step": step,
                        "epoch": epoch + 1,
                        "loss": sum(recent) / len(recent),
                        "lr": optimizer.param_groups[0]["lr"],
                        "seconds": round(time.time() - started),
                    }
                )
                if cfg.max_steps is not None and step >= cfg.max_steps:
                    stopped = True
                if step % cfg.save_every == 0 and not last:
                    save(epoch, index + 1)
            if stopped:
                break
        if stopped:
            break
        scores = evaluate(model, val, device, amp) if val else {"loss": float("nan")}
        log(
            {
                "kind": "epoch",
                "epoch": epoch + 1,
                "step": step,
                "train_loss": sum(losses) / len(losses),
                **{f"val_{k}": v for k, v in scores.items()},
            }
        )
        score = scores["loss"] if val else sum(losses) / len(losses)
        epoch, pos = epoch + 1, 0
        if score < best:
            best = score
            model.save_pretrained(str(cfg.out / "_best_tmp"))
            copy_adapter(cfg.out / "_best_tmp", cfg.out / "best")
            shutil.rmtree(cfg.out / "_best_tmp")
        save(epoch, 0)

    if stopped or not (cfg.out / "best").exists():  # a smoke run, or nothing beat infinity
        model.save_pretrained(str(cfg.out / "_last_tmp"))
        copy_adapter(cfg.out / "_last_tmp", cfg.out / "last")
        shutil.rmtree(cfg.out / "_last_tmp")
    metrics.close()
    summary = {"steps": step, "epochs_done": epoch, "best_val_loss": best, "stopped_early": stopped}
    (cfg.out / "run.json").write_text(
        json.dumps({"config": {k: str(v) for k, v in asdict(cfg).items()}, **summary}, indent=1)
    )
    write_model_card(cfg, summary)
    return summary


def write_model_card(cfg: TrainConfig, summary: dict[str, Any]) -> None:
    manifest_path = cfg.dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    counts = manifest.get("counts", {})
    card = f"""# Adapter {cfg.out.name}

- Base model: `{cfg.base}` (4-bit NF4: {cfg.load_4bit}).
- Method: QLoRA on the language model's linear layers, r={cfg.rank}, alpha={cfg.alpha},
  dropout {cfg.dropout}, LR {cfg.lr} (cosine, {cfg.warmup_ratio:.0%} warm-up), {cfg.epochs} epochs,
  {cfg.grad_accum} samples per optimizer step, seed {cfg.seed}.
- Data: dataset `{cfg.dataset.name}`; samples {counts}.
  Frames sha256 `{manifest.get("frames_sha256", "n/a")}`.
  Labels sha256 `{manifest.get("source_labels_sha256", "n/a")}`.
- Trained {summary["steps"]} optimizer steps; best validation loss {summary["best_val_loss"]:.4f}
  {"(stopped early: a smoke run, not a trained adapter)" if summary["stopped_early"] else ""}.

## Limits

Validation loss is a training signal, not a result. Whether this adapter beats the zero-shot model
is `ml/evaluation/reasoning/` on the test split, which this run did not touch. The data comes from
the annotated clips only; behaviour on other cameras, lighting or event types is not known.
"""
    (cfg.out / "model_card.md").write_text(card)


def upload(out: Path, uri: str) -> list[str]:
    """Upload the best (else last) adapter under `out` and its model card to `s3://bucket/prefix/`."""
    import asyncio  # noqa: PLC0415

    from vms_common.config import StorageSettings  # noqa: PLC0415
    from vms_common.storage.s3 import S3Client  # noqa: PLC0415

    folder = out / "best" if (out / "best").exists() else out / "last"
    storage = StorageSettings()
    client = S3Client(
        endpoint_url=storage.endpoint_url, access_key=storage.access_key,
        secret_key=storage.secret_key, region=storage.region,
    )  # fmt: skip
    sent = []

    async def go() -> None:
        for name in (*ADAPTER_FILES, "../model_card.md"):
            source = (folder / name).resolve()
            target = f"{uri.rstrip('/')}/{source.name}"
            await client.upload_file(target, str(source))
            sent.append(target)

    asyncio.run(go())
    return sent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dataset", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--base", default=TrainConfig.base)
    ap.add_argument("--epochs", type=int, default=TrainConfig.epochs)
    ap.add_argument("--lr", type=float, default=TrainConfig.lr)
    ap.add_argument("--rank", type=int, default=TrainConfig.rank)
    ap.add_argument("--alpha", type=int, default=TrainConfig.alpha)
    ap.add_argument("--grad-accum", type=int, default=TrainConfig.grad_accum)
    ap.add_argument("--seed", type=int, default=TrainConfig.seed)
    ap.add_argument(
        "--no-4bit", action="store_true", help="fp16 base (a small model, or a big GPU)"
    )
    ap.add_argument("--no-grad-checkpointing", action="store_true")
    ap.add_argument("--save-every", type=int, default=TrainConfig.save_every)
    ap.add_argument("--max-steps", type=int, default=None, help="stop after N steps (smoke test)")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--upload", metavar="S3_URI", help="after training, e.g. s3://vms-models/tg/v1")
    ap.add_argument(
        "--upload-only",
        metavar="S3_URI",
        help="train nothing: upload what --out already holds (an adapter trained on Kaggle)",
    )
    args = ap.parse_args()
    if args.upload_only:
        print("uploaded:", upload(args.out, args.upload_only))
        return
    if args.dataset is None:
        ap.error("--dataset is required unless --upload-only")
    cfg = TrainConfig(
        dataset=args.dataset, out=args.out, base=args.base, epochs=args.epochs, lr=args.lr,
        rank=args.rank, alpha=args.alpha, grad_accum=args.grad_accum, seed=args.seed,
        load_4bit=not args.no_4bit, grad_checkpointing=not args.no_grad_checkpointing,
        save_every=args.save_every, max_steps=args.max_steps, resume=args.resume,
    )  # fmt: skip
    summary = train(cfg)
    print(json.dumps(summary))
    if args.upload:
        print("uploaded:", upload(cfg.out, args.upload))


if __name__ == "__main__":
    main()
