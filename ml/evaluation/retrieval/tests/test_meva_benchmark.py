"""Unit tests for the MEVA retrieval benchmark's pure functions. `make test` does not collect `ml/`;
run them with `uv run --package vms-retrieval pytest ml/evaluation/retrieval/tests`."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "meva_benchmark", Path(__file__).parent.parent / "meva_benchmark.py"
)
assert SPEC and SPEC.loader
mb = importlib.util.module_from_spec(SPEC)
sys.modules["meva_benchmark"] = mb  # a dataclass looks its module up here
SPEC.loader.exec_module(mb)


def clip(name: str, activity: str, start: float, end: float):
    return mb.Clip(name, activity, start, end)


def test_overlap_is_the_shared_length_and_never_negative() -> None:
    assert mb.overlap(0, 10, 5, 20) == 5
    assert mb.overlap(0, 10, 10, 20) == 0
    assert mb.overlap(0, 10, 12, 20) == 0


def test_queries_must_match_the_labels_one_to_one() -> None:
    clips = [clip("ex0-a", "a", 0, 5), clip("ex1-b", "b", 6, 9), clip("ex2-b", "b", 10, 12)]
    mb.check_queries([{"activity": "a"}, {"activity": "b"}], clips)
    for bad in (
        [{"activity": "a"}],  # b has no query
        [{"activity": "a"}, {"activity": "b"}, {"activity": "c"}],  # c has no label
        [{"activity": "a"}, {"activity": "b"}, {"activity": "b"}],  # b asked twice
    ):
        with pytest.raises(SystemExit):
            mb.check_queries(bad, clips)


def test_calibration_finds_when_the_stream_began() -> None:
    clips = [
        clip("c0", "x", 20, 30),
        clip("c1", "y", 35, 50),
        clip("c2", "x", 58, 64),
        clip("c3", "z", 70, 90),
        clip("c4", "y", 95, 100),
    ]
    true_t0 = 1_000_000.0
    # ingestion joined 12 s late; perception tracked people only while a clip was on
    tracks = [(true_t0 + c.start_s + 1, true_t0 + c.end_s - 1) for c in clips]
    cal = mb.calibrate(tracks, clips, first_segment_ts=true_t0 + 12)
    assert cal["t0"] == pytest.approx(true_t0, abs=1.0)
    assert cal["score"] > 1.5 * cal["runner_up_score"]  # the margin the benchmark itself demands
    assert cal["presence_inside_clips"] > 0.95
    assert cal["late_join_s"] == pytest.approx(12, abs=1.0)


def test_query_metrics_on_a_hand_checked_ranking() -> None:
    spans = [(100.0, 112.0), (300.0, 310.0)]  # the activity's two clips
    ranked = [
        (0.0, 10.0),  # not relevant
        (95.0, 105.0),  # overlaps clip 1 by 5 s
        (111.0, 121.0),  # overlaps clip 1 by 1 s only: not relevant
        (305.0, 315.0),  # overlaps clip 2 by 5 s
    ]
    m = mb.query_metrics(ranked, spans, ks=(1, 2, 4))
    assert m["first_relevant_rank"] == 2
    assert m["rr"] == 0.5
    assert (m["hit@1"], m["hit@2"], m["hit@4"]) == (0.0, 1.0, 1.0)
    assert (m["p@1"], m["p@2"], m["p@4"]) == (0.0, 0.5, 0.5)
    assert (m["clips@1"], m["clips@2"], m["clips@4"]) == (0.0, 0.5, 1.0)


def test_a_query_with_no_relevant_window_scores_zero() -> None:
    m = mb.query_metrics([(0.0, 10.0), (20.0, 30.0)], [(100.0, 110.0)], ks=(2,))
    assert m["first_relevant_rank"] is None
    assert (m["rr"], m["hit@2"], m["p@2"], m["clips@2"]) == (0.0, 0.0, 0.0, 0.0)


def test_random_baseline_matches_the_closed_form() -> None:
    b = mb.random_baseline(10, 2, ks=(1, 8, 9))
    assert b["hit@1"] == pytest.approx(0.2)
    assert b["hit@8"] == pytest.approx(1 - 1 / 45)  # the only miss: all 8 irrelevant windows
    assert b["hit@9"] == pytest.approx(1.0)  # 9 draws cannot avoid both relevant windows
    assert b["p@1"] == pytest.approx(0.2)


def test_the_report_renders_for_a_minimal_run() -> None:
    row = {
        "activity": "a",
        "family": "f",
        "query": "q",
        "n_clips": 1,
        "n_relevant_windows": 2,
        "n_results": 3,
        "wall_s": 0.5,
        "notes": [],
        "on_any_clip": 1.0,
        "baseline": mb.random_baseline(20, 2),
        **mb.query_metrics([(0.0, 10.0)], [(0.0, 10.0)]),
    }
    report = {
        "finished_at": "now",
        "camera": "meva-ex",
        "n_clips": 1,
        "n_activities": 1,
        "stream_minutes": 1.0,
        "n_windows": 20,
        "calibration": {
            "score": 10,
            "runner_up_score": 2,
            "presence_inside_clips": 0.9,
            "late_join_s": 3.0,
        },
        "modes": {"fast": {"rows": [row], "summary": mb.summarise([row])}},
    }
    text = mb.markdown(report)
    assert "## fast mode" in text and "| a | 1 | 1 |" in text
