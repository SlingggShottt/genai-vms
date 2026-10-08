"""Hand-checked values for the SUS scorer and the session summary."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "usability_sus", Path(__file__).resolve().parents[1] / "sus.py"
)
assert spec and spec.loader
sus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sus)

BEST = [
    5,
    1,
    5,
    1,
    5,
    1,
    5,
    1,
    5,
    1,
]  # agrees with every positive item, disagrees with every negative


def test_the_scale_scores_the_best_possible_answers_100_and_a_neutral_one_50() -> None:
    assert sus.sus_score(BEST) == 100.0
    assert sus.sus_score([3] * 10) == 50.0
    assert sus.sus_score([1, 5, 1, 5, 1, 5, 1, 5, 1, 5]) == 0.0  # the worst possible


def test_straight_lining_cancels_out_because_half_the_items_are_reversed() -> None:
    assert sus.sus_score([5] * 10) == 50.0
    assert sus.sus_score([1] * 10) == 50.0


def test_a_mixed_sheet_is_scored_item_by_item() -> None:
    # odd items 4,4,5,4,5 -> 3+3+4+3+4 = 17; even items 2,1,2,2,1 -> 3+4+3+3+4 = 17; 34 * 2.5
    assert sus.sus_score([4, 2, 4, 1, 5, 2, 4, 2, 5, 1]) == 85.0


def test_a_sheet_that_cannot_be_scored_is_refused() -> None:
    with pytest.raises(ValueError, match="10 items"):
        sus.sus_score([3] * 9)
    with pytest.raises(ValueError, match="1 to 5"):
        sus.sus_score([3] * 9 + [6])
    with pytest.raises(ValueError, match="1 to 5"):
        sus.sus_score([3] * 9 + [0])


def test_the_bands_change_at_their_published_edges() -> None:
    assert [sus.band(x) for x in (100, 85.5, 85.4, 72.75, 72.7, 52, 51.9, 38, 37.9, 0)] == [
        "excellent", "excellent", "good", "good", "ok", "ok", "poor", "poor", "worst imaginable",
        "worst imaginable",
    ]  # fmt: skip


def write(path: Path, header: str, rows: list[str]) -> Path:
    path.write_text(header + "\n" + "\n".join(rows) + "\n")
    return path


SUS_HEADER = (
    "participant," + ",".join(f"q{i}" for i in range(1, 11)) + ",most_confusing,would_not_lose"
)


def test_sus_rows_are_read_by_participant_and_a_bad_row_is_named(tmp_path: Path) -> None:
    good = write(
        tmp_path / "sus.csv",
        SUS_HEADER,
        ["P01,5,1,5,1,5,1,5,1,5,1,,", "P02,3,3,3,3,3,3,3,3,3,3,,", ",1,1,1,1,1,1,1,1,1,1,,"],
    )
    assert sus.read_sus(good) == {
        "P01": 100.0,
        "P02": 50.0,
    }  # the row with no participant is skipped
    bad = write(
        tmp_path / "bad.csv", SUS_HEADER, ["P01,5,1,5,1,5,1,5,1,5,1,,", "P07,3,3,x,3,3,3,3,3,3,3,,"]
    )
    with pytest.raises(ValueError, match="P07"):
        sus.read_sus(bad)


TASK_HEADER = (
    "participant,role,experience_with_cctv_or_vms,task,success,time_s,wrong_turns,times_helped,"
    "what_the_observer_said,notes"
)


def test_task_rows_keep_only_valid_outcomes(tmp_path: Path) -> None:
    path = write(
        tmp_path / "tasks.csv",
        TASK_HEADER,
        [
            "P01,op,high,search,1,95,0,0,,",
            "P02,op,low,search,0.5,200,2,1,hint about the toggle,",
            "P03,op,low,search,,,,,,",  # not run
            "P04,op,low,search,2,10,0,0,,",  # not a valid outcome
            "P05,op,low,,1,10,0,0,,",  # no task name
            "P06,op,low,alert,0,240,3,2,,",
        ],
    )
    got = sus.read_tasks(path)
    assert sorted(got) == ["alert", "search"] and len(got["search"]) == 2
    assert got["search"][1] == {"success": 0.5, "time_s": 200.0, "wrong_turns": 2.0, "helped": 1.0}


def test_the_session_summary_is_the_hand_computed_one(tmp_path: Path) -> None:
    tasks = {
        "search": [
            {"success": 1.0, "time_s": 95.0, "wrong_turns": 0.0, "helped": 0.0},
            {"success": 0.5, "time_s": 200.0, "wrong_turns": 2.0, "helped": 1.0},
        ],
        "alert": [{"success": 0.0, "time_s": None, "wrong_turns": 3.0, "helped": 2.0}],
    }
    s = sus.summarise({"P01": 100.0, "P02": 50.0, "P03": 85.0}, tasks)
    assert s["participants"] == 3 and s["sus"]["mean"] == pytest.approx(78.333, abs=1e-3)
    assert (s["sus"]["min"], s["sus"]["max"], s["sus"]["band"]) == (50.0, 100.0, "good")
    assert s["sus"]["small_group"] is True
    assert s["tasks"]["search"] == {
        "attempts": 2, "success_rate": 0.75, "completed_fully": 1, "median_time_s": 147.5,
        "wrong_turns_mean": 1.0, "needed_help": 1,
    }  # fmt: skip
    assert s["tasks"]["alert"]["median_time_s"] is None and s["tasks"]["alert"]["needed_help"] == 1


def test_the_report_warns_about_a_small_group_and_handles_no_data() -> None:
    small = sus.markdown(sus.summarise({"P01": 70.0}, {}))
    assert "fewer than 5 participants" in small and "SUS 70.0" in small
    large = sus.markdown(sus.summarise({f"P{i}": 70.0 + i for i in range(6)}, {}))
    assert "fewer than 5" not in large
    assert "No SUS scores yet" in sus.markdown(sus.summarise({}, {}))
