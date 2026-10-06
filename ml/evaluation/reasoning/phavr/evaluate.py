"""PhaVR evaluation (P5-J3): how good are the captions and VQA answers for one stage of one view?

    uv run python ml/evaluation/reasoning/phavr/evaluate.py --dataset datasets/phavr-v1 \
        --split test --methods template,model --label "zero-shot qwen2.5vl:3b"

Runs on a dataset made by `ml/training/phavr/build_dataset.py`. Two methods, scored the same way:

- `template`: no model. A caption made of the event type and the stage, and "Cannot tell" for every
  question. The floor: a model that does not beat this has learned nothing about the pictures.
- `model`: the sample's prompt and frames go to the `phase_vr` task of the real gateway; the answer
  is parsed and cleaned by the reasoning service's own `ViewDraft` / `clean_answers`, so an answer
  outside the question's vocabulary counts as unanswered, exactly as it would be dropped in
  production. Point it at the zero-shot base or, once trained, the adapter (`--label` names it).

Captions are scored with BLEU-4 (corpus), ROUGE-L, CIDEr-D and `meteor_exact` against the one
verified caption (see `caption_metrics.py`: not the published METEOR, which needs downloads). VQA
is scored per question: accuracy over the questions asked, how often the answer was missing, and
how often it said "Cannot tell" (honest) or answered what the reference could not tell (a claim
without evidence). Figures that are means over samples carry a 95 % bootstrap interval.

What it does not do: judge whether a caption is true (only how close it is to the verified one),
or compare against a cloud model (`--task` can name one; nothing here sets it up).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # for `stats`
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for `metrics`

import caption_metrics as metrics  # noqa: E402
from reasoning.steps.readings import ViewDraft, clean_answers  # noqa: E402
from stats import mean_ci  # noqa: E402
from vms_common.llm import ImageInput, LLMError  # noqa: E402
from vms_common.vqa_bank import CANNOT_TELL, VQABank, load_vqa_bank  # noqa: E402

REPO = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class Sample:
    id: str
    event_type: str
    phase: str
    primary_view: bool
    caption: str
    answers: list[tuple[str, str]]  # the reference: (question id, canonical answer)
    prompt: str
    images: list[Path]


def load_samples(dataset: Path, split: str) -> list[Sample]:
    out = []
    for line in (dataset / f"{split}.jsonl").read_text().splitlines():
        r = json.loads(line)
        user = r["messages"][0]["content"]
        out.append(
            Sample(
                id=r["id"],
                event_type=r["event_type"],
                phase=r["phase"],
                primary_view=r["primary_view"],
                caption=r["caption"],
                answers=[(a["id"], a["answer"]) for a in r["answers"]],
                prompt=next(c["text"] for c in user if c["type"] == "text"),
                images=[dataset / p for p in r["images"]],
            )
        )
    return out


# ---- predictors ---------------------------------------------------------------------------------


@dataclass
class Prediction:
    caption: str
    answers: list[tuple[str, str]]
    seconds: float = 0.0
    error: str = ""


def template_prediction(s: Sample) -> Prediction:
    kind = s.event_type.replace("_", " ")
    caption = f"A person is visible during the {s.phase} stage of a {kind}."
    return Prediction(caption, [(qid, CANNOT_TELL) for qid, _ in s.answers])


class Gateway(Protocol):
    async def vision(self, task: str, prompt: str, images: list[ImageInput], **kw): ...


async def model_prediction(gateway: Gateway, task: str, bank: VQABank, s: Sample) -> Prediction:
    started = time.perf_counter()
    try:
        images = [ImageInput(data=p.read_bytes()) for p in s.images]
        result = await gateway.vision(task, s.prompt, images, response_model=ViewDraft)
    except LLMError as exc:
        return Prediction("", [], time.perf_counter() - started, str(exc)[:120])
    draft = result.parsed
    questions = [bank.question(qid) for qid, _ in s.answers]
    cleaned = [(qid, value) for qid, _text, value in clean_answers(draft, questions)]
    return Prediction(draft.caption.strip(), cleaned, time.perf_counter() - started)


# ---- scoring ------------------------------------------------------------------------------------


def corpus_bleu_ci(
    hyps: list[list[str]], refs: list[list[str]], seed: int = 0, n: int = 1000
) -> dict:
    """Corpus BLEU-4 and a 95 % interval from resampling whole samples."""
    point = metrics.bleu(hyps, refs)
    if len(hyps) < 2:
        return {"n": len(hyps), "mean": round(point, 3), "ci95": [float("nan"), float("nan")]}
    rng = random.Random(seed)  # noqa: S311 - resampling, not security
    idx = range(len(hyps))
    draws = sorted(
        metrics.bleu([hyps[i] for i in pick], [refs[i] for i in pick])
        for pick in ([rng.choice(idx) for _ in idx] for _ in range(n))
    )
    return {
        "n": len(hyps),
        "mean": round(point, 3),
        "ci95": [round(draws[int(0.025 * n)], 3), round(draws[int(0.975 * n) - 1], 3)],
    }


@dataclass
class Scores:
    samples: list[Sample] = field(default_factory=list)
    preds: list[Prediction] = field(default_factory=list)

    def add(self, s: Sample, p: Prediction) -> None:
        self.samples.append(s)
        self.preds.append(p)

    def summary(self) -> dict:
        hyps = [metrics.tokens(p.caption) for p in self.preds]
        refs = [metrics.tokens(s.caption) for s in self.samples]
        rouge = [metrics.rouge_l(h, r) for h, r in zip(hyps, refs, strict=True)]
        meteor = [metrics.meteor_exact(h, r) for h, r in zip(hyps, refs, strict=True)]
        cider = metrics.cider_d(hyps, refs)
        counts = [
            metrics.vqa_counts(s.answers, p.answers)
            for s, p in zip(self.samples, self.preds, strict=True)
        ]
        asked = sum(c["asked"] for c in counts) or 1
        per_sample_acc = [c["correct"] / c["asked"] for c in counts if c["asked"]]

        def share(key: str) -> float:
            return round(sum(c[key] for c in counts) / asked, 3)

        by: dict[str, dict] = {}
        for label, keyer in (
            ("phase", lambda s: s.phase),
            ("view", lambda s: "primary view" if s.primary_view else "other view"),
        ):
            for group in sorted({keyer(s) for s in self.samples}):
                ids = [i for i, s in enumerate(self.samples) if keyer(s) == group]
                by[f"{label}: {group}"] = {
                    "rouge_l": mean_ci([rouge[i] for i in ids]),
                    "vqa_accuracy": mean_ci(
                        [
                            counts[i]["correct"] / counts[i]["asked"]
                            for i in ids
                            if counts[i]["asked"]
                        ]
                    ),
                }
        seconds = [p.seconds for p in self.preds if p.seconds]
        return {
            "bleu4": corpus_bleu_ci(hyps, refs),
            "cider_d": mean_ci(cider),
            "rouge_l": mean_ci(rouge),
            "meteor_exact": mean_ci(meteor),
            "vqa_accuracy": mean_ci(per_sample_acc),
            "vqa_share_unanswered": share("unanswered"),
            "vqa_share_cannot_tell": share("cannot_tell_said"),
            "vqa_share_answered_what_the_reference_could_not_tell": share(
                "answered_what_the_reference_could_not_tell"
            ),
            "seconds_per_sample_median": round(statistics.median(seconds), 2) if seconds else None,
            "gateway_errors": sum(bool(p.error) for p in self.preds),
            "by": by,
        }


async def evaluate(
    samples: list[Sample],
    methods: list[str],
    gateway: Gateway | None,
    task: str,
    label: str,
    bank: VQABank,
) -> dict:
    out: dict = {"samples": len(samples), "methods": {}}
    if "template" in methods:
        sc = Scores()
        for s in samples:
            sc.add(s, template_prediction(s))
        out["methods"]["template (no model)"] = sc.summary()
    if "model" in methods:
        if gateway is None:
            raise ValueError("the model method needs a gateway")
        sc = Scores()
        for i, s in enumerate(samples, 1):
            sc.add(s, await model_prediction(gateway, task, bank, s))
            print(f"  model {i}/{len(samples)}", flush=True)
        out["methods"][label] = sc.summary()
    return out


def markdown(report: dict, dataset: str, split: str) -> str:
    def cell(d: dict | None) -> str:
        if not d or d["mean"] is None:
            return "–"
        return f"{d['mean']} ({d['ci95'][0]}–{d['ci95'][1]}, n={d['n']})"

    lines = [
        f"# PhaVR evaluation — `{dataset}` / `{split}` ({report['samples']} samples)",
        "",
        "Captions against the one verified caption; `meteor_exact` matches identical words only "
        "(not the published METEOR). Means over samples with a 95 % bootstrap interval; BLEU-4 is "
        "corpus-level. VQA accuracy counts an unanswered or out-of-vocabulary answer as wrong.",
        "",
        "| method | BLEU-4 | CIDEr-D | ROUGE-L | METEOR-exact | VQA accuracy |",
        "|---|---|---|---|---|---|",
    ]
    for name, m in report["methods"].items():
        lines.append(
            f"| {name} | {cell(m['bleu4'])} | {cell(m['cider_d'])} | {cell(m['rouge_l'])} | "
            f"{cell(m['meteor_exact'])} | {cell(m['vqa_accuracy'])} |"
        )
    for name, m in report["methods"].items():
        lines += [
            "",
            f"## {name}",
            "",
            f'Questions unanswered {m["vqa_share_unanswered"]}, answered "Cannot tell" '
            f"{m['vqa_share_cannot_tell']}, answered where the reference could not tell "
            f"{m['vqa_share_answered_what_the_reference_could_not_tell']} (shares of questions "
            f"asked); {m['gateway_errors']} gateway errors; median "
            f"{m['seconds_per_sample_median'] or '–'} s per sample.",
            "",
            "| by | ROUGE-L | VQA accuracy |",
            "|---|---|---|",
        ]
        for group, v in m["by"].items():
            lines.append(f"| {group} | {cell(v['rouge_l'])} | {cell(v['vqa_accuracy'])} |")
    return "\n".join(lines) + "\n"


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--split", default="test")
    ap.add_argument("--methods", default="template,model")
    ap.add_argument("--label", default="model (zero-shot)")
    ap.add_argument("--task", default="phase_vr")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--redis-url", default="redis://localhost:6379/9", help="scratch db: lease + cache"
    )
    ap.add_argument("--out", type=Path, default=None, help="write <out>.json and <out>.md")
    args = ap.parse_args()

    samples = load_samples(args.dataset, args.split)
    if args.limit:
        samples = samples[: args.limit]
    methods = args.methods.split(",")
    bank = load_vqa_bank(REPO / "config" / "vqa_bank.yaml")
    gateway = redis = None
    if "model" in methods:
        from redis.asyncio import Redis
        from vms_common.config import LLMSettings
        from vms_common.llm import LLMGateway

        redis = Redis.from_url(args.redis_url, decode_responses=True)
        await redis.flushdb()  # a cached answer would be timed as a model call
        gateway = LLMGateway.from_settings(LLMSettings(), redis=redis)
    try:
        report = await evaluate(samples, methods, gateway, args.task, args.label, bank)
    finally:
        if gateway is not None:
            await gateway.aclose()
        if redis is not None:
            await redis.flushdb()
            await redis.aclose()
    text = markdown(report, args.dataset.name, args.split)
    print(text)
    if args.out:
        args.out.with_suffix(".json").write_text(json.dumps(report, indent=1) + "\n")
        args.out.with_suffix(".md").write_text(text)


if __name__ == "__main__":
    asyncio.run(main())
