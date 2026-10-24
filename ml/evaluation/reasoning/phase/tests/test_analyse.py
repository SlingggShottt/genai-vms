"""analyse.py: what a finished run's table hides."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from PIL import Image

HERE = Path(__file__).resolve().parent


def load(name: str, path: Path):  # noqa: ANN201
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


an = load("tg_analyse_under_test", HERE.parent / "analyse.py")
ev = an.ev

TRUTH = [("baseline", 0.0, 4.5), ("action", 4.5, 10.0)]


def sample(tmp_path: Path, sid: str, *, frames: int = 4, source: str = "human:from-scratch"):  # noqa: ANN201
    times = [10.0 * k / (frames - 1) for k in range(frames)]
    path = tmp_path / "f.jpg"
    Image.new("RGB", (4, 4)).save(path)
    return ev.Sample(
        id=sid, event_type="robbery", n_views=1, window_s=10.0, frame_times=times,
        labels=ev.labels_at(TRUTH, times), truth=TRUTH, flagged=(4.5, 10.0), prompt="p",
        images=[path] * frames, label_source=source,
    )  # fmt: skip


def answer(spans, usable=True, labels=None, error=""):  # noqa: ANN001, ANN201
    return ev.Prediction(spans, usable, labels, 1.0, error)


PERFECT = [("baseline", 0.0, 4.5), ("action", 4.5, 10.0)]
POOR = [("action", 0.0, 10.0)]


def test_only_the_answers_the_model_gave_are_compared_with_the_rules(tmp_path: Path) -> None:
    samples = {i: sample(tmp_path, i) for i in "abc"}
    rules = ev.sample_miou(TRUTH, ev.rules_spans(samples["a"]))  # the rules timeline is not exact
    preds = {
        "a": answer(PERFECT, labels=["baseline", "baseline", "action", "action"]),
        "b": answer(POOR, labels=["action"] * 4),
        "c": answer(ev.rules_spans(samples["c"]), usable=False),  # borrowed from the rules
    }
    r = an.analyse(samples, preds)
    assert (r["samples"], r["answered"], r["answered_share"]) == (3, 2, 0.667)
    assert r["model_miou_on_answered"] == pytest.approx(
        (1.0 + ev.sample_miou(TRUTH, POOR)) / 2, abs=1e-3
    )
    assert r["rules_miou_on_same"] == pytest.approx(rules, abs=1e-3)  # c is not in this mean
    assert 0 < rules < 1


def test_it_counts_who_wins_loses_and_ties(tmp_path: Path) -> None:
    samples = {i: sample(tmp_path, i) for i in "abc"}
    preds = {
        "a": answer(PERFECT, labels=[]),  # better than the rules
        "b": answer([("precursor", 0.0, 10.0)], labels=[]),  # no stage in common with the truth
        "c": answer(ev.rules_spans(samples["c"]), labels=[]),  # exactly the rules
    }
    r = an.analyse(samples, preds)
    assert (r["model_better"], r["model_worse"], r["ties"]) == (1, 1, 1)


def test_the_stages_the_model_says_are_counted_against_the_true_ones(tmp_path: Path) -> None:
    samples = {"a": sample(tmp_path, "a")}
    preds = {"a": answer(PERFECT, labels=["baseline", "action", "action", "action"])}
    r = an.analyse(samples, preds)
    assert r["stages_the_model_said"] == {"action": 3, "baseline": 1}
    assert r["stages_true_on_those"] == {"action": 2, "baseline": 2}
    assert "escalation" not in r["stages_the_model_said"]


def test_failures_are_split_by_how_many_frames_were_shown(tmp_path: Path) -> None:
    samples = {
        "a": sample(tmp_path, "a", frames=4), "b": sample(tmp_path, "b", frames=8),
        "c": sample(tmp_path, "c", frames=8), "d": sample(tmp_path, "d", frames=8),
    }  # fmt: skip
    ok = answer(PERFECT, labels=[])
    bad = answer(PERFECT, usable=False)
    r = an.analyse(samples, {"a": ok, "b": bad, "c": bad, "d": ok})
    assert r["unanswered_by_frames"] == {4: "0/1", 8: "2/3"}


def test_gateway_errors_are_counted_separately_from_unusable_answers(tmp_path: Path) -> None:
    samples = {i: sample(tmp_path, i) for i in "ab"}
    preds = {
        "a": answer(PERFECT, usable=False, error="timeout"),
        "b": answer(PERFECT, usable=False),
    }
    assert an.analyse(samples, preds)["gateway_errors"] == 1


def test_scores_are_split_by_who_made_the_labels(tmp_path: Path) -> None:
    samples = {
        "a": sample(tmp_path, "a", source="human:from-scratch"),
        "b": sample(tmp_path, "b", source="draft:v2:padding-rule"),
    }
    preds = {i: answer(PERFECT, labels=[]) for i in samples}
    r = an.analyse(samples, preds)
    assert (
        set(r["by_source"]) == {"human", "model draft (rule only)"}
        and r["by_source"]["human"]["n"] == 1
    )


def test_a_run_that_is_not_finished_is_refused_not_averaged(tmp_path: Path) -> None:
    samples = {i: sample(tmp_path, i) for i in "ab"}
    with pytest.raises(ValueError, match="1 samples have no answer"):
        an.analyse(samples, {"a": answer(PERFECT, labels=[])})


def test_nothing_answered_gives_no_means_not_a_crash(tmp_path: Path) -> None:
    samples = {"a": sample(tmp_path, "a")}
    r = an.analyse(samples, {"a": answer(PERFECT, usable=False)})
    assert r["answered"] == 0 and r["model_miou_on_answered"] is None and r["by_source"] == {}


def test_the_text_says_the_numbers_a_reader_needs(tmp_path: Path) -> None:
    samples = {i: sample(tmp_path, i) for i in "ab"}
    preds = {"a": answer(POOR, labels=["action"] * 4), "b": answer(PERFECT, usable=False)}
    text = an.markdown(an.analyse(samples, preds))
    assert "1 of 2 samples got a usable answer from the model (50%)" in text
    assert "better on 1, worse on 0, equal on 0" in text and "| 4 | 1/2 |" in text


def test_the_exact_source_keeps_a_persons_accepted_drafts_apart_from_their_own_marks(
    tmp_path: Path,
) -> None:
    sources = {
        "a": "human:from-scratch", "b": "human:accepted-draft:claude-draft-1",
        "c": "human:corrected-draft:claude-draft-1", "d": "draft:claude-draft-2:padding-rule",
        "e": "dataset-span:ucf-crime",
    }  # fmt: skip
    samples = {i: sample(tmp_path, i, source=src) for i, src in sources.items()}
    r = an.analyse(samples, {i: answer(PERFECT, labels=[]) for i in samples})
    assert set(r["by_exact_source"]) == {
        "human:from-scratch", "human:accepted-draft", "human:corrected-draft",
        "draft:padding-rule", "dataset-span:ucf-crime",
    }  # fmt: skip
    assert r["by_exact_source"]["human:accepted-draft"]["n"] == 1
    assert set(r["by_source"]) == {"human", "model draft (rule only)", "dataset span"}


def test_the_exact_source_drops_the_version_but_not_what_matters() -> None:
    assert an._exact("human:accepted-draft:v1") == "human:accepted-draft"
    assert an._exact("human:from-scratch") == "human:from-scratch"
    assert an._exact("draft:v2:zoomed-frames") == "draft:zoomed-frames"
    assert an._exact("draft:v1:frames") == "draft:frames"
    assert an._exact("dataset-span:ucf-crime") == "dataset-span:ucf-crime"
    assert an._exact("") == ""
