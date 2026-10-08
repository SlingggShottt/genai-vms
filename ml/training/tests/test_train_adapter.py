"""The adapter trainer (P5-D2 / P5-J2): its arithmetic and data handling without a model, and a
full tiny run (learn, resume exactly, write what `hf_local` loads) where a tokenizer is cached."""

from __future__ import annotations

import glob
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("train_adapter", ROOT / "train_adapter.py")
assert spec and spec.loader
ta = importlib.util.module_from_spec(spec)
sys.modules["train_adapter"] = ta
spec.loader.exec_module(ta)


# ---- arithmetic -----------------------------------------------------------------------------


def test_the_learning_rate_warms_up_then_follows_a_cosine_to_zero() -> None:
    lrs = [ta.lr_at(s, 100, base_lr=2e-4, warmup_ratio=0.1) for s in range(100)]
    assert lrs[0] == pytest.approx(2e-5)  # one tenth of the way through a 10-step warm-up
    assert lrs[:10] == sorted(lrs[:10]) and lrs[9] == pytest.approx(2e-4)
    assert lrs[10] == pytest.approx(2e-4)  # the peak, then it comes down
    assert lrs[10:] == sorted(lrs[10:], reverse=True)
    assert lrs[55] == pytest.approx(1e-4, rel=0.05)  # halfway down at the midpoint
    assert 0 <= lrs[-1] < 1e-6 and min(lrs) >= 0


def test_a_run_shorter_than_its_warm_up_still_has_a_positive_rate() -> None:
    assert ta.lr_at(0, 2, base_lr=1e-3, warmup_ratio=0.05) > 0


def test_an_epochs_order_depends_on_the_seed_and_the_epoch_only() -> None:
    order = ta.epoch_order(20, 0, 7)
    assert sorted(order) == list(range(20))
    assert order == ta.epoch_order(20, 0, 7)  # what makes a resumed run see the same data
    assert order != ta.epoch_order(20, 1, 7) and order != ta.epoch_order(20, 0, 8)


def test_the_labels_are_the_answer_and_nothing_of_the_prompt() -> None:
    assert ta.labels_for([5, 6, 7, 8, 9], 3) == [-100, -100, -100, 8, 9]
    assert ta.labels_for([5, 6], 0) == [5, 6]


def test_optimizer_steps_per_epoch_round_up() -> None:
    assert [ta.steps_per_epoch(n, 8) for n in (1, 8, 9, 16, 17)] == [1, 1, 2, 2, 3]


def test_adapters_go_on_the_language_model_only() -> None:
    pattern = re.compile(ta.TARGET_MODULES)
    for name in (
        "model.language_model.layers.3.self_attn.q_proj",
        "model.layers.0.mlp.down_proj",
        "base_model.model.model.language_model.layers.35.mlp.gate_proj",
    ):
        assert pattern.fullmatch(name), name
    for name in (
        "model.visual.blocks.2.mlp.gate_proj",
        "visual.blocks.0.attn.proj",
        "model.language_model.layers.3.input_layernorm",
        "lm_head",
        "model.language_model.embed_tokens",
    ):
        assert not pattern.fullmatch(name), name


# ---- samples --------------------------------------------------------------------------------

SAMPLE = {
    "id": "c|cam01",
    "images": ["frames/c/cam01/00.jpg", "frames/c/cam01/01.jpg"],
    "messages": [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": "frames/c/cam01/00.jpg"},
                {"type": "image", "image": "frames/c/cam01/01.jpg"},
                {"type": "text", "text": "Label the frames."},
            ],
        },
        {"role": "assistant", "content": [{"type": "text", "text": '{"phases": ["a", "b"]}'}]},
    ],
}


def test_image_parts_become_placeholders_and_the_text_stays() -> None:
    messages = ta.template_messages(SAMPLE)
    assert [p["type"] for p in messages[0]["content"]] == ["image", "image", "text"]
    assert all("image" not in p for p in messages[0]["content"] if p["type"] == "image")
    assert messages[1]["content"] == [{"type": "text", "text": '{"phases": ["a", "b"]}'}]
    plain = ta.template_messages({"messages": [{"role": "user", "content": "hi"}]})
    assert plain == [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]


def test_a_missing_split_is_empty_not_an_error(tmp_path: Path) -> None:
    assert ta.read_split(tmp_path, "val") == []
    (tmp_path / "train.jsonl").write_text(
        json.dumps({"a": 1}) + "\n\n" + json.dumps({"a": 2}) + "\n"
    )
    assert ta.read_split(tmp_path, "train") == [{"a": 1}, {"a": 2}]


class FakeProcessor:
    """Text in, one id per whitespace-separated word out: enough to see what is masked."""

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        assert tokenize is False
        words = []
        for m in messages:
            if m["role"] == "assistant":
                words.append("<assistant>")  # the template opens the reply before its text
            words += [
                "<img>" if p["type"] == "image" else p["text"].replace(" ", "_")
                for p in m["content"]
            ]
        if add_generation_prompt:
            words.append("<assistant>")
        return " ".join(words)

    def __call__(self, *, text, images, return_tensors):
        import torch

        ids = [hash(w) % 1000 for w in text[0].split()]
        return {
            "input_ids": torch.tensor([ids]),
            "attention_mask": torch.ones(1, len(ids), dtype=torch.long),
        }


def test_an_example_masks_the_prompt_and_keeps_the_answer(tmp_path: Path) -> None:
    pytest.importorskip("torch")
    from PIL import Image

    for rel in SAMPLE["images"]:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 8)).save(tmp_path / rel)
    example = ta.build_example(SAMPLE, tmp_path, FakeProcessor())
    ids, labels = example["input_ids"][0].tolist(), example["labels"][0].tolist()
    prompt_len = 4  # two images, the question, the generation prompt
    assert labels[:prompt_len] == [-100] * prompt_len
    assert labels[prompt_len:] == ids[prompt_len:] and len(ids) == prompt_len + 1


def test_the_model_card_says_what_was_trained_and_what_it_does_not_show(tmp_path: Path) -> None:
    ds = tmp_path / "tg-v1"
    ds.mkdir()
    (ds / "manifest.json").write_text(
        json.dumps(
            {"counts": {"train": 8}, "frames_sha256": "f" * 8, "source_labels_sha256": "l" * 8}
        )
    )
    out = tmp_path / "out"
    out.mkdir()
    cfg = ta.TrainConfig(dataset=ds, out=out, epochs=2)
    ta.write_model_card(
        cfg, {"steps": 6, "epochs_done": 2, "best_val_loss": 0.5, "stopped_early": False}
    )
    card = (out / "model_card.md").read_text()
    assert "Qwen/Qwen2.5-VL-3B-Instruct" in card and "r=16" in card and "{'train': 8}" in card
    assert "ffffffff" in card and "best validation loss 0.5000" in card
    assert "not a trained adapter" not in card and "did not touch" in card
    ta.write_model_card(
        cfg, {"steps": 2, "epochs_done": 0, "best_val_loss": 9.0, "stopped_early": True}
    )
    assert "not a trained adapter" in (out / "model_card.md").read_text()


# ---- a whole tiny run -----------------------------------------------------------------------

SNAPSHOT = glob.glob(
    str(Path.home() / ".cache/huggingface/hub/models--Qwen--Qwen2.5-VL-3B-Instruct/snapshots/*")
)


def _tiny_model_dir(tmp: Path) -> Path:
    """A 10 M-parameter random Qwen2.5-VL with the real config shape and the real tokenizer."""
    import torch
    from transformers import AutoConfig, AutoModelForImageTextToText, AutoProcessor

    cfg = AutoConfig.from_pretrained(SNAPSHOT[0])
    t, v = cfg.text_config, cfg.vision_config
    t.hidden_size, t.intermediate_size, t.num_hidden_layers = 64, 128, 2
    t.num_attention_heads, t.num_key_value_heads = 4, 2
    t.rope_scaling = {"type": "mrope", "rope_type": "default", "mrope_section": [2, 3, 3]}
    if getattr(t, "layer_types", None):
        t.layer_types = ["full_attention"] * 2
    if getattr(t, "max_window_layers", None) is not None:
        t.max_window_layers = 2
    v.depth, v.hidden_size, v.intermediate_size, v.num_heads, v.out_hidden_size = 2, 64, 128, 4, 64
    v.fullatt_block_indexes = [1]
    for k in (
        "hidden_size",
        "intermediate_size",
        "num_hidden_layers",
        "num_attention_heads",
        "num_key_value_heads",
    ):
        if hasattr(cfg, k) and hasattr(t, k):
            setattr(cfg, k, getattr(t, k))
    cfg.rope_scaling = t.rope_scaling
    torch.manual_seed(0)
    out = tmp / "tiny"
    AutoModelForImageTextToText.from_config(cfg, dtype=torch.float32).save_pretrained(out)
    AutoProcessor.from_pretrained(SNAPSHOT[0]).save_pretrained(out)
    return out


def _tiny_dataset(root: Path) -> Path:
    import random

    from PIL import Image

    rng = random.Random(1)  # noqa: S311 - noise for test images
    root.mkdir(parents=True)
    answer = '{"phases": ["baseline", "action"]}'
    for split, n in (("train", 6), ("val", 2)):
        rows = []
        for i in range(n):
            rels = []
            for k in range(2):
                rel = f"frames/{split}{i}/{k}.jpg"
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                Image.effect_noise((56, 56), rng.randint(20, 120)).convert("RGB").save(root / rel)
                rels.append(rel)
            rows.append(
                {
                    "id": f"{split}{i}",
                    "images": rels,
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"type": "image", "image": r} for r in rels]
                            + [{"type": "text", "text": "Label each frame."}],
                        },
                        {"role": "assistant", "content": [{"type": "text", "text": answer}]},
                    ],
                }
            )
        (root / f"{split}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return root


@pytest.mark.skipif(not SNAPSHOT, reason="needs the Qwen2.5-VL tokenizer in the Hugging Face cache")
def test_a_tiny_run_learns_resumes_exactly_and_writes_what_hf_local_loads(tmp_path: Path) -> None:
    pytest.importorskip("peft")
    torch = pytest.importorskip("torch")
    from safetensors.torch import load_file

    model = _tiny_model_dir(tmp_path)
    data = _tiny_dataset(tmp_path / "ds")

    def cfg(name: str, **kw):
        return ta.TrainConfig(
            dataset=data, out=tmp_path / name, base=str(model), load_4bit=False,
            grad_checkpointing=False, lr=3e-3, rank=4, alpha=8, grad_accum=2, save_every=2, **kw,
        )  # fmt: skip

    whole = ta.train(cfg("whole", epochs=4))
    metrics = [
        json.loads(x) for x in (tmp_path / "whole" / "metrics.jsonl").read_text().splitlines()
    ]
    epochs = [m for m in metrics if m["kind"] == "epoch"]
    assert epochs[-1]["train_loss"] < epochs[0]["train_loss"], "it does not learn"
    assert whole["epochs_done"] == 4 and not whole["stopped_early"]
    for name in ta.ADAPTER_FILES:  # exactly what hf_local fetches
        assert (tmp_path / "whole" / "best" / name).is_file()
    assert (tmp_path / "whole" / "model_card.md").is_file()

    trained = load_file(tmp_path / "whole" / "best" / "adapter_model.safetensors")
    assert not [k for k in trained if "visual" in k], "the vision tower got an adapter"
    modules = {
        m for k in trained for m in ("q", "k", "v", "o", "gate", "up", "down") if f".{m}_proj." in k
    }
    assert modules == {"q", "k", "v", "o", "gate", "up", "down"}  # every linear of the text model

    cut = ta.train(cfg("cut", epochs=4, max_steps=5))  # interrupted mid-epoch
    assert cut["stopped_early"] and cut["steps"] == 5
    done = ta.train(cfg("cut", epochs=4, resume=True))
    assert done["steps"] == whole["steps"] and done["best_val_loss"] == pytest.approx(
        whole["best_val_loss"], rel=1e-4
    )
    a = load_file(tmp_path / "whole" / "checkpoint" / "adapter" / "adapter_model.safetensors")
    b = load_file(tmp_path / "cut" / "checkpoint" / "adapter" / "adapter_model.safetensors")
    assert max(float((a[k] - b[k]).abs().max()) for k in a) < 1e-4, "a resumed run differs"
    assert torch is not None
