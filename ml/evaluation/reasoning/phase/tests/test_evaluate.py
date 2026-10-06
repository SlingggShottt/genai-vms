"""Unit tests for the TG evaluation: hand-checked metrics, both predictors, the fallbacks, and that
it reads samples exactly as the dataset builder writes them. No model, no network."""

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
ev = load("tg_evaluate", HERE.parent / "evaluate.py")
bd = load("tg_build_dataset_for_eval", HERE.parents[3] / "training" / "tg" / "build_dataset.py")

TRUTH = [("baseline", 0.0, 4.0), ("action", 4.0, 8.0)]
# a 10 s window whose handover (4.5) is not where 4 evenly spread frames put it (5.0)
TRUTH_M = [("baseline", 0.0, 4.5), ("action", 4.5, 10.0)]


def sample(
    tmp_path: Path, *, n_frames: int = 4, window: float = 8.0, truth=None, flagged=(4.0, 6.0)
):
    """A sample whose frames are tiny pictures on disk."""
    truth = truth or TRUTH
    times = [window * k / (n_frames - 1) for k in range(n_frames)]
    images = []
    for k in range(n_frames):
        path = tmp_path / f"f{k}.jpg"
        Image.new("RGB", (8, 8), (k * 40, 0, 0)).save(path)
        images.append(path)
    labels = ev.labels_at(truth, times)
    return ev.Sample(
        id="c|cam", event_type="intrusion", n_views=1, window_s=window, frame_times=times,
        labels=labels, truth=truth, flagged=flagged, prompt="PROMPT", images=images,
    )  # fmt: skip


# ---- metrics ------------------------------------------------------------------------------------


def test_a_perfect_answer_scores_one_and_a_shifted_boundary_costs_what_it_should() -> None:
    assert ev.sample_miou(TRUTH, TRUTH) == 1.0
    shifted = [("baseline", 0.0, 5.0), ("action", 5.0, 8.0)]
    # baseline: 4 shared of 5 = 0.8; action: 3 shared of 4 = 0.75
    assert ev.stage_iou(TRUTH, shifted) == {
        "baseline": pytest.approx(0.8),
        "action": pytest.approx(0.75),
    }
    assert ev.sample_miou(TRUTH, shifted) == pytest.approx(0.775)


def test_a_stage_the_answer_invents_or_misses_counts_as_zero() -> None:
    only_baseline = [("baseline", 0.0, 8.0)]
    iou = ev.stage_iou(TRUTH, only_baseline)
    assert iou["action"] == 0.0 and iou["baseline"] == pytest.approx(0.5)
    invented = [("baseline", 0.0, 4.0), ("precursor", 4.0, 6.0), ("action", 6.0, 8.0)]
    assert ev.stage_iou(TRUTH, invented)["precursor"] == 0.0
    assert ev.sample_miou(TRUTH, invented) == pytest.approx((1.0 + 0.0 + 0.5) / 3)


def test_boundary_error_is_per_shared_handover_and_missing_ones_are_counted() -> None:
    assert ev.boundary_errors(TRUTH, [("baseline", 0.0, 5.0), ("action", 5.0, 8.0)]) == ([1.0], 0)
    # the answer never reaches `action`, so the baseline->action handover is not in it
    assert ev.boundary_errors(TRUTH, [("baseline", 0.0, 8.0)]) == ([], 1)
    # a different pair of stages is not the same boundary
    three = [("baseline", 0.0, 3.0), ("escalation", 3.0, 5.0), ("action", 5.0, 8.0)]
    assert ev.boundary_errors(TRUTH, three) == ([], 1)


def test_labels_at_follows_the_spans_and_takes_the_nearest_outside_them() -> None:
    assert ev.labels_at(TRUTH, [0.0, 3.9, 4.0, 7.9]) == ["baseline", "baseline", "action", "action"]
    assert ev.labels_at(TRUTH, [8.0, 9.5]) == ["action", "action"]


def test_the_bootstrap_interval_is_seeded_and_brackets_the_mean() -> None:
    values = [0.2, 0.4, 0.5, 0.9, 0.7, 0.1, 0.6]
    lo, hi = ev.bootstrap_ci(values, seed=1)
    assert (lo, hi) == ev.bootstrap_ci(values, seed=1)
    assert lo <= sum(values) / len(values) <= hi
    assert all(x != x for x in ev.bootstrap_ci([0.5]))  # nan for a single value


# ---- predictors ---------------------------------------------------------------------------------


def test_the_rules_timeline_is_the_services_own(tmp_path: Path) -> None:
    spans = ev.rules_spans(sample(tmp_path, window=10.0, flagged=(5.0, 7.0)))
    assert spans == [
        ("precursor", 0.0, 2.0),
        ("escalation", 2.0, 5.0),
        ("action", 5.0, 7.0),
        ("aftermath", 7.0, 10.0),
    ]


async def test_a_good_model_answer_becomes_spans_and_is_usable(tmp_path: Path) -> None:
    s = sample(tmp_path, window=10.0, truth=TRUTH_M)  # frames at 0, 3.33, 6.67, 10
    gateway = FakeGateway({"phase_tg": {"phases": ["baseline", "baseline", "action", "action"]}})
    p = await ev.model_prediction(gateway, "phase_tg", s)
    assert p.usable and p.labels == ["baseline", "baseline", "action", "action"]
    assert [x[0] for x in p.spans] == ["baseline", "action"]
    assert p.spans[0][2] == pytest.approx(5.0)  # halfway between the 2nd and 3rd frame
    assert gateway.calls[0].prompt == "PROMPT" and len(gateway.calls[0].images) == 4


async def test_an_unusable_answer_falls_back_to_the_rules_timeline(tmp_path: Path) -> None:
    s = sample(tmp_path)
    one_stage = FakeGateway(
        {"phase_tg": {"phases": ["action"] * 4}}
    )  # tells nothing about boundaries
    p = await ev.model_prediction(one_stage, "phase_tg", s)
    assert not p.usable and p.spans == ev.rules_spans(s) and p.labels == ["action"] * 4
    wrong_length = FakeGateway({"phase_tg": {"phases": ["baseline", "action"]}})
    p = await ev.model_prediction(wrong_length, "phase_tg", s)
    assert not p.usable and p.spans == ev.rules_spans(s) and p.labels is None


async def test_a_gateway_error_is_counted_and_falls_back(tmp_path: Path) -> None:
    class Down:
        async def vision(self, *a, **k):
            raise LLMError("no model")

    p = await ev.model_prediction(Down(), "phase_tg", sample(tmp_path))
    assert not p.usable and p.error == "no model" and p.spans == ev.rules_spans(sample(tmp_path))


# ---- the whole evaluation -----------------------------------------------------------------------


async def test_the_evaluation_scores_both_methods_and_tells_them_apart(tmp_path: Path) -> None:
    samples = [sample(tmp_path, window=10.0, truth=TRUTH_M)] * 3
    good = {"phases": ["baseline", "baseline", "action", "action"]}
    perfect = FakeGateway({"phase_tg": [good, good, {"phases": ["action"] * 4}]})
    report = await ev.evaluate(samples, ["rules", "model"], perfect, "phase_tg", "demo model")
    rules, model = (
        report["methods"]["rules (detector timing, no model)"],
        report["methods"]["demo model"],
    )
    assert report["samples"] == 3 and model["usable_answer_rate"]["mean"] == pytest.approx(
        2 / 3, abs=1e-3
    )
    assert model["frame_accuracy"]["n"] == 2  # only usable answers have a frame accuracy
    assert model["frame_accuracy"]["mean"] == 1.0
    assert rules["usable_answer_rate"] is None and rules["seconds_per_sample_median"] is None
    # the unusable third answer was replaced by the rules timeline, so it scores the rules' mIoU
    assert 0.0 < model_good_miou() < 1.0  # the good answers are close, not exact
    assert model["miou"]["mean"] == pytest.approx(
        (2 * model_good_miou() + rules["miou"]["mean"]) / 3, abs=2e-3
    )
    assert model["miou"]["mean"] > rules["miou"]["mean"]  # and better than the detector timing here
    assert set(model["miou_by_event_type"]) == {"intrusion"} and set(model["miou_by_views"]) == {
        "1 view"
    }


def model_good_miou() -> float:
    """What the two good answers score: the handover at 5.0 against a true 4.5 in a 10 s window."""
    return ev.sample_miou(TRUTH_M, [("baseline", 0.0, 5.0), ("action", 5.0, 10.0)])


async def test_the_model_method_without_a_gateway_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="gateway"):
        await ev.evaluate([sample(tmp_path)], ["model"], None, "phase_tg", "x")


def test_the_report_renders_a_table_and_breakdowns() -> None:
    cell = {"n": 3, "mean": 0.5, "ci95": [0.2, 0.8]}
    method = {
        "miou": cell, "boundary_mae_s": cell, "frame_accuracy": cell, "usable_answer_rate": cell,
        "seconds_per_sample_median": 1.2, "boundaries_not_in_answer": 2, "gateway_errors": 0,
        "miou_by_event_type": {"intrusion": cell}, "miou_by_views": {"1 view": cell},
    }  # fmt: skip
    text = ev.markdown({"samples": 3, "methods": {"m": method}}, "tg-v1", "test")
    assert (
        "| m | 0.5 (0.2–0.8, n=3) |" in text
        and "| intrusion |" in text
        and "2 true boundaries" in text
    )


# ---- it reads what the builder writes -----------------------------------------------------------


def test_samples_load_exactly_as_the_builder_writes_them(tmp_path: Path) -> None:
    line = {
        "schema_version": "phase_labels.v1", "clip_id": "c1", "source_video": "s1",
        "event_type": "intrusion", "primary_view": "cam01",
        "views": [{"camera": "cam01", "video_uri": "x"}, {"camera": "cam02", "video_uri": "y"}],
        "phases": [
            {"phase": "baseline", "start_s": 0.0, "end_s": 4.0},
            {"phase": "action", "start_s": 4.0, "end_s": 8.0},
        ],
    }  # fmt: skip
    clip = bd.PhaseLabelClip.model_validate(line)
    times = [0.0, 3.0, 5.0, 7.0]
    labels, _ = bd.label_frames(times, clip)
    record = bd.sample_record(
        clip, "cam01", "test", times, labels, (4.0, 6.0), [f"frames/{k}.jpg" for k in range(4)]
    )
    (tmp_path / "test.jsonl").write_text(json.dumps(record) + "\n")
    [s] = ev.load_samples(tmp_path, "test")
    assert (s.id, s.event_type, s.n_views, s.window_s) == ("c1|cam01", "intrusion", 2, 8.0)
    assert s.truth == [("baseline", 0.0, 4.0), ("action", 4.0, 8.0)] and s.flagged == (4.0, 6.0)
    assert s.labels == labels and s.frame_times == times
    assert s.prompt == bd.render_user_prompt(clip, "cam01", times, (4.0, 6.0))
    assert s.images == [tmp_path / f"frames/{k}.jpg" for k in range(4)]
