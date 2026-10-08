"""Tests for the PhaVR evaluation driver: it reads samples as the builder writes them, scores a
scripted gateway, and treats bad answers as the reasoning service does. No model, no network."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from PIL import Image
from vms_common.llm import LLMError
from vms_common.llm.testing import FakeGateway


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve().parent
ev = load("phavr_evaluate", HERE.parent / "evaluate.py")
builder = load(
    "phavr_builder_for_eval", HERE.parents[3] / "training" / "phavr" / "build_dataset.py"
)
BANK = builder.load_vqa_bank(builder.REPO / "config" / "vqa_bank.yaml")
QUESTIONS = BANK.questions_for("intrusion")[:3]

CAPTIONS = {
    "baseline": "A man in a red coat stands near the gate.",
    "action": "Two women carry bags towards the open door.",
    "aftermath": "A dog sleeps beside the empty bench.",
}


def label(phase: str, view: str = "cam01"):
    items = [{"id": q.id, "q": q.text, "a": q.answers[0]} for q in QUESTIONS]
    return builder.PhavrLabel.model_validate(
        {
            "schema_version": "phavr_label.v1", "clip_id": "c", "source_video": "s",
            "event_type": "intrusion", "view": view, "phase": phase, "start_s": 0.0, "end_s": 4.0,
            "caption": CAPTIONS[phase], "vqa": items, "pseudo": None, "edits": None,
            "annotator": "K",
        }
    )  # fmt: skip


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    """A `test.jsonl` of three samples written with the builder's own `sample_record`."""
    rows = []
    for i, (phase, view) in enumerate(
        [("baseline", "cam01"), ("action", "cam01"), ("aftermath", "cam02")]
    ):
        lab = label(phase, view)
        images = []
        for k in range(2):
            path = tmp_path / "frames" / f"{i}_{k}.jpg"
            path.parent.mkdir(exist_ok=True)
            Image.new("RGB", (8, 8), (i * 60, k * 60, 0)).save(path)
            images.append(str(path.relative_to(tmp_path)))
        asked = [(q, q.answers[0]) for q in QUESTIONS]
        rows.append(
            builder.sample_record(
                lab, "test", [0.0, 2.0], asked, images, primary_view=view == "cam01"
            )
        )
    (tmp_path / "test.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return tmp_path


def right_answer(phase: str, ids=None) -> dict:
    ids = ids or [q.id for q in QUESTIONS]
    return {
        "caption": CAPTIONS[phase],
        "answers": [{"id": i, "answer": BANK.question(i).answers[0]} for i in ids],
    }


# ---- reading ------------------------------------------------------------------------------------


def test_samples_load_as_the_builder_writes_them(dataset: Path) -> None:
    samples = ev.load_samples(dataset, "test")
    assert [s.phase for s in samples] == ["baseline", "action", "aftermath"]
    assert [s.primary_view for s in samples] == [True, True, False]
    assert samples[0].caption == CAPTIONS["baseline"]
    assert samples[0].answers == [(q.id, q.answers[0]) for q in QUESTIONS]
    assert "Questions:" in samples[0].prompt and samples[0].images[0].is_file()


# ---- predictors ---------------------------------------------------------------------------------


def test_the_template_baseline_says_cannot_tell_to_everything(dataset: Path) -> None:
    s = ev.load_samples(dataset, "test")[1]
    p = ev.template_prediction(s)
    assert p.caption == "A person is visible during the action stage of a intrusion."
    assert p.answers == [(q.id, "Cannot tell") for q in QUESTIONS]


async def test_a_model_answer_is_cleaned_like_the_service_cleans_it(dataset: Path) -> None:
    s = ev.load_samples(dataset, "test")[0]
    answer = right_answer("baseline")
    answer["answers"][0]["answer"] = answer["answers"][0]["answer"].upper() + "."  # case and a stop
    answer["answers"][1]["answer"] = "Probably"  # outside the vocabulary: dropped
    answer["answers"].append({"id": "intrusion.no_such_question", "answer": "Yes"})  # not asked
    gateway = FakeGateway({"phase_vr": answer})
    p = await ev.model_prediction(gateway, "phase_vr", BANK, s)
    assert p.caption == CAPTIONS["baseline"]
    assert p.answers == [
        (QUESTIONS[0].id, QUESTIONS[0].answers[0]),
        (QUESTIONS[2].id, QUESTIONS[2].answers[0]),
    ]
    assert gateway.calls[0].prompt == s.prompt and len(gateway.calls[0].images) == 2


async def test_a_gateway_error_gives_an_empty_answer_and_is_counted(dataset: Path) -> None:
    class Down:
        async def vision(self, *a, **k):
            raise LLMError("no model")

    s = ev.load_samples(dataset, "test")[0]
    p = await ev.model_prediction(Down(), "phase_vr", BANK, s)
    assert (p.caption, p.answers, p.error) == ("", [], "no model")


# ---- the whole evaluation -----------------------------------------------------------------------


async def test_a_perfect_model_scores_one_everywhere_but_cider_and_the_template_does_not(
    dataset: Path,
) -> None:
    samples = ev.load_samples(dataset, "test")
    gateway = FakeGateway(
        {"phase_vr": [right_answer("baseline"), right_answer("action"), right_answer("aftermath")]}
    )
    report = await ev.evaluate(samples, ["template", "model"], gateway, "phase_vr", "perfect", BANK)
    model, template = report["methods"]["perfect"], report["methods"]["template (no model)"]
    assert model["rouge_l"]["mean"] == 1.0 and model["vqa_accuracy"]["mean"] == 1.0
    assert model["bleu4"]["mean"] == 1.0 and model["cider_d"]["mean"] == pytest.approx(
        10.0, abs=1e-2
    )
    assert model["vqa_share_unanswered"] == 0 and model["gateway_errors"] == 0
    assert template["vqa_accuracy"]["mean"] == 0.0 and template["vqa_share_cannot_tell"] == 1.0
    assert template["rouge_l"]["mean"] < model["rouge_l"]["mean"]
    assert template["seconds_per_sample_median"] is None
    assert set(model["by"]) == {
        "phase: action", "phase: aftermath", "phase: baseline",
        "view: other view", "view: primary view",
    }  # fmt: skip


async def test_unanswered_and_failed_samples_pull_the_scores_down(dataset: Path) -> None:
    samples = ev.load_samples(dataset, "test")
    half = right_answer("baseline", ids=[QUESTIONS[0].id])  # answers one of three questions
    bad_vocab = right_answer("action")
    bad_vocab["answers"][0]["answer"] = "Probably"

    class Flaky:
        def __init__(self) -> None:
            self.queue = [half, bad_vocab]

        async def vision(self, *a, **k):
            if not self.queue:
                raise LLMError("gone")
            return await FakeGateway({"phase_vr": self.queue.pop(0)}).vision(*a, **k)

    report = await ev.evaluate(samples, ["model"], Flaky(), "phase_vr", "flaky", BANK)
    m = report["methods"]["flaky"]
    assert m["gateway_errors"] == 1
    # asked 9; answered right: 1 + 2 + 0 -> 3/9 correct; unanswered: 2 + 1 + 3 = 6
    assert m["vqa_share_unanswered"] == pytest.approx(6 / 9, abs=1e-3)
    assert m["vqa_accuracy"]["mean"] == pytest.approx((1 / 3 + 2 / 3 + 0) / 3, abs=1e-3)
    assert m["rouge_l"]["mean"] == pytest.approx(
        2 / 3, abs=1e-3
    )  # the failed sample's caption is empty


async def test_the_model_method_needs_a_gateway(dataset: Path) -> None:
    with pytest.raises(ValueError, match="gateway"):
        await ev.evaluate(ev.load_samples(dataset, "test"), ["model"], None, "phase_vr", "x", BANK)


def test_corpus_bleu_interval_is_seeded_and_brackets_the_point_estimate() -> None:
    hyps = [
        ev.metrics.tokens(x)
        for x in ("the cat sat on the mat today", "a dog ran in the park now") * 4
    ]
    refs = [
        ev.metrics.tokens(x)
        for x in ("the cat sat on the rug today", "a dog ran in the yard now") * 4
    ]
    a = ev.corpus_bleu_ci(hyps, refs, seed=3)
    assert a == ev.corpus_bleu_ci(hyps, refs, seed=3)
    assert a["ci95"][0] <= a["mean"] <= a["ci95"][1] and a["n"] == 8


def test_the_report_renders() -> None:
    cell = {"n": 3, "mean": 0.5, "ci95": [0.2, 0.8]}
    method = {
        "bleu4": cell, "cider_d": cell, "rouge_l": cell, "meteor_exact": cell, "vqa_accuracy": cell,
        "vqa_share_unanswered": 0.1, "vqa_share_cannot_tell": 0.2,
        "vqa_share_answered_what_the_reference_could_not_tell": 0.0,
        "seconds_per_sample_median": 1.5, "gateway_errors": 0,
        "by": {"phase: action": {"rouge_l": cell, "vqa_accuracy": cell}},
    }  # fmt: skip
    text = ev.markdown({"samples": 3, "methods": {"m": method}}, "phavr-v1", "test")
    assert "| m | 0.5 (0.2–0.8, n=3) |" in text and "| phase: action |" in text
    assert "published METEOR" in text
