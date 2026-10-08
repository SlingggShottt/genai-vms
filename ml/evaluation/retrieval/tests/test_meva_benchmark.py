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


CLIPS = [
    clip("c0", "x", 20, 30),
    clip("c1", "y", 35, 50),
    clip("c2", "x", 58, 64),
    clip("c3", "z", 70, 90),
    clip("c4", "y", 95, 100),
]
TRUE_T0 = 1_000_000.0


def tracks_like_perception() -> list[tuple[float, float]]:
    """A track begins a moment after each clip starts (the scene cut), more begin later in the clip,
    and every track lingers 4 s into the black gap after it: the tracker keeps it alive."""
    out = []
    for c in CLIPS:
        out.append((TRUE_T0 + c.start_s + 0.6, TRUE_T0 + c.end_s + 4))
        out.append((TRUE_T0 + c.start_s + 1.1, TRUE_T0 + c.end_s + 4))
        out.append((TRUE_T0 + c.start_s + 0.5 * (c.end_s - c.start_s), TRUE_T0 + c.end_s + 4))
    return out


def test_calibration_finds_when_the_stream_began_despite_lingering_tracks() -> None:
    # ingestion joined 12 s late; a score built on where tracks END would come out ~4 s late
    cal = mb.calibrate(tracks_like_perception(), CLIPS, first_segment_ts=TRUE_T0 + 12)
    assert cal["t0"] == pytest.approx(TRUE_T0, abs=1.0)
    assert cal["score"] > 1.5 * cal["runner_up_score"]  # the margin the benchmark itself demands
    assert cal["tracks_starting_in_black"] == 0
    assert cal["late_join_s"] == pytest.approx(12, abs=1.0)


def test_tracks_that_begin_anywhere_inside_clips_still_pin_the_start() -> None:
    """New people walk in mid-clip. Nothing is tracked in black, so the start is where no track
    begins in a gap: the penalty for starts in black is what finds it (the reward for starts
    just after a clip's start is flat for this data)."""
    tracks = []
    for c in CLIPS:
        t = c.start_s + 0.3
        while t < c.end_s - 0.3:
            tracks.append((TRUE_T0 + t, TRUE_T0 + t + 3))
            t += 0.7
    cal = mb.calibrate(tracks, CLIPS, first_segment_ts=TRUE_T0 + 12)
    assert cal["t0"] == pytest.approx(TRUE_T0, abs=0.5)
    assert cal["tracks_starting_in_black"] == 0


def test_tracks_that_begin_in_black_lower_the_score_and_are_reported() -> None:
    clean = tracks_like_perception()
    noisy = [
        *clean,
        *[(TRUE_T0 + s, TRUE_T0 + s + 2) for s in (10.0, 32.0, 53.0, 66.0)],
    ]  # in black
    a = mb.calibrate(clean, CLIPS, first_segment_ts=TRUE_T0 + 12)
    b = mb.calibrate(noisy, CLIPS, first_segment_ts=TRUE_T0 + 12)
    assert b["t0"] == pytest.approx(a["t0"])
    assert b["score"] == a["score"] - 4  # each costs one point
    assert b["tracks_starting_in_black"] == pytest.approx(4 / len(noisy))


def test_a_prior_window_restricts_where_the_start_is_searched() -> None:
    tracks = tracks_like_perception()
    inside = mb.calibrate(tracks, CLIPS, TRUE_T0 + 12, prior=(TRUE_T0 - 1, TRUE_T0 + 8))
    assert inside["t0"] == pytest.approx(TRUE_T0, abs=1.0) and inside["used_prior"]
    # a window that excludes the truth cannot find it
    wrong = mb.calibrate(tracks, CLIPS, TRUE_T0 + 12, prior=(TRUE_T0 + 40, TRUE_T0 + 50))
    assert abs(wrong["t0"] - TRUE_T0) > 10


def test_only_the_latest_contiguous_recording_is_used() -> None:
    segs = [(0.0, 10.0), (10.0, 20.0), (5000.0, 5010.0), (5010.0, 5020.0)]
    tracks = [(3.0, 8.0), (12.0, 15.0), (5003.0, 5008.0), (5012.0, 5014.0)]
    kept_segs, kept_tracks = mb.latest_recording(segs, tracks)
    assert kept_segs == segs[2:]
    assert kept_tracks == tracks[2:]


def test_the_simulator_start_is_taken_only_when_it_fits_the_recording(tmp_path: Path) -> None:
    first = 2_000_000_000.0  # epoch seconds of the first segment
    iso = "2033-05-18T03:33:20+00:00"  # = 2_000_000_000 s
    assert mb.replay_start("2033-05-18T03:33:00+00:00", first) == pytest.approx(first - 20)
    assert mb.replay_start(iso, first - 400) is None  # later than the first segment: not this run
    assert mb.replay_start("2033-05-18T03:20:00+00:00", first) is None  # over 2 minutes earlier
    assert mb.replay_start("not a time", first) is None
    f = tmp_path / "start"
    f.write_text("2033-05-18T03:33:10+00:00\n")
    assert mb.replay_start(str(f), first) == pytest.approx(first - 10)


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
            "tracks_starting_in_black": 0.1,
            "used_prior": False,
            "late_join_s": 3.0,
        },
        "modes": {"fast": {"rows": [row], "summary": mb.summarise([row])}},
    }
    text = mb.markdown(report)
    assert "## fast mode" in text and "| a | 1 | 1 |" in text
