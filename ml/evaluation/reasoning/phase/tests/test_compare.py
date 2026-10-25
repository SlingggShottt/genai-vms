"""compare.py: two runs on the same clips, paired."""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def load(name: str, path: Path):  # noqa: ANN201
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cmp = load("tg_compare_under_test", HERE.parent / "compare.py")
ev = cmp.ev

TRUTH = [("baseline", 0.0, 5.0), ("action", 5.0, 10.0)]
RIGHT = [("baseline", 0.0, 5.0), ("action", 5.0, 10.0)]  # mIoU 1.0
HALF = [("baseline", 0.0, 7.5), ("action", 7.5, 10.0)]  # mIoU 7/12: (5/7.5 + 2.5/5) / 2
HALF_MIOU = 7 / 12
GAP = 1 - HALF_MIOU


def sample(sid: str, source: str):  # noqa: ANN201
    return ev.Sample(
        id=sid, event_type="activity", n_views=1, window_s=10.0, frame_times=[0.0, 5.0],
        labels=["baseline", "action"], truth=TRUTH, flagged=(5.0, 10.0), prompt="", images=[],
        label_source=source,
    )  # fmt: skip


def answer(spans):  # noqa: ANN001, ANN201
    return ev.Prediction(spans, True, None, 1.0, None)


def test_the_difference_is_taken_clip_by_clip_and_split_by_label_source() -> None:
    samples = {
        "h1": sample("h1", "human:from-scratch"),
        "h2": sample("h2", "human:corrected-draft:v1"),
        "r1": sample("r1", "draft:v1:padding-rule"),
        "r2": sample("r2", "draft:v1:padding-rule"),
    }
    a = {"h1": answer(HALF), "h2": answer(RIGHT), "r1": answer(HALF), "r2": answer(HALF)}
    b = {"h1": answer(RIGHT), "h2": answer(HALF), "r1": answer(RIGHT), "r2": answer(RIGHT)}

    result = cmp.compare(samples, a, b)

    assert result["all clips"]["n"] == 4
    assert result["all clips"]["difference"] == pytest.approx((GAP - GAP + GAP + GAP) / 4)
    assert result["all clips"]["b_better"] == 3 and result["all clips"]["b_worse"] == 1
    human = result["human"]
    assert (human["a"], human["b"], human["difference"]) == pytest.approx(
        ((HALF_MIOU + 1) / 2, (HALF_MIOU + 1) / 2, 0.0)
    )
    rule = result["model draft (rule only)"]
    assert rule["difference"] == pytest.approx(GAP) and rule["b_better"] == 2
    assert rule["a"] == pytest.approx(HALF_MIOU) and rule["b"] == pytest.approx(1.0)


def test_a_difference_under_a_point_is_a_tie() -> None:
    near = [("baseline", 0.0, 5.02), ("action", 5.02, 10.0)]
    result = cmp.compare(
        {"x": sample("x", "dataset-span:ucf-crime")}, {"x": answer(RIGHT)}, {"x": answer(near)}
    )
    row = result["all clips"]
    assert (row["b_better"], row["tied"], row["b_worse"]) == (0, 1, 0)


def test_a_clip_missing_from_one_run_is_an_error_not_a_smaller_sample() -> None:
    samples = {"x": sample("x", "human:from-scratch"), "y": sample("y", "human:from-scratch")}
    with pytest.raises(ValueError, match="1 clips lack an answer"):
        cmp.compare(samples, {"x": answer(RIGHT), "y": answer(RIGHT)}, {"x": answer(RIGHT)})


def test_one_clip_gives_a_difference_but_no_interval() -> None:
    result = cmp.compare(
        {"x": sample("x", "human:from-scratch")}, {"x": answer(HALF)}, {"x": answer(RIGHT)}
    )
    row = result["human"]
    assert row["difference"] == pytest.approx(GAP) and math.isnan(row["ci95"][0])
    assert "n/a" in cmp.markdown(result, ("a", "b"))


def test_the_table_reads_b_minus_a_with_all_clips_first() -> None:
    samples = {"h": sample("h", "human:from-scratch"), "r": sample("r", "draft:v1:padding-rule")}
    result = cmp.compare(
        samples, {"h": answer(HALF), "r": answer(HALF)}, {"h": answer(RIGHT), "r": answer(RIGHT)}
    )
    lines = cmp.markdown(result, ("zero-shot", "adapter")).splitlines()
    assert "adapter − zero-shot" in lines[0]
    assert lines[2].startswith("| all clips | 2 | 0.583 | 1.000 | +0.417 (")
