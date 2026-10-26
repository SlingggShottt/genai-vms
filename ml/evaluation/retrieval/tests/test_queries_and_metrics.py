"""queries.jsonl validation and the retrieval metrics (P4-J6). Pure functions, no services.
`uv run --package vms-retrieval pytest ml/evaluation/retrieval/tests`"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent.parent


def load(name: str):  # noqa: ANN201
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


qs = load("queries")
mt = load("metrics")


def line(**over) -> str:  # noqa: ANN003
    base = {
        "id": "q1", "query": "a person gets into a car", "kind": "explicit",
        "label": "enter-vehicle", "filters": {"cameras": ["meva-ex"]},
        "relevant": [{"camera": "meva-ex", "start_s": 10.0, "end_s": 20.0}],
    }  # fmt: skip
    return json.dumps({**base, **over})


def check(*lines: str) -> list[str]:
    return qs.problems([qs.parse(x) for x in lines])


# ---- queries.jsonl ----------------------------------------------------------------------------


def test_a_good_line_has_nothing_wrong_with_it() -> None:
    assert check(line()) == []


def test_relevant_places_may_be_on_the_recordings_clock_or_absolute() -> None:
    absolute = {
        "camera": "cam02",
        "start": "2026-10-25T09:30:00+00:00",
        "end": "2026-10-25T09:30:20+00:00",
    }
    q = qs.parse(line(relevant=[absolute], filters={"cameras": ["cam02"]}))
    assert qs.problems([q]) == []
    assert q.relevant[0].relative is False and q.relevant[0].end - q.relevant[0].start == 20
    assert qs.parse(line()).relevant[0].relative is True


@pytest.mark.parametrize(
    "over,expected",
    [
        ({"id": ""}, "no id"),
        ({"query": "a"}, "2 to 500 characters"),
        ({"kind": "obvious"}, "kind must be one of"),
        ({"relevant": []}, "no relevant place"),
        (
            {"relevant": [{"camera": "meva-ex", "start_s": 20, "end_s": 10}]},
            "ends before it starts",
        ),
        ({"relevant": [{"camera": "meva-ex", "start_s": 1}]}, "cannot be read"),
        (
            {
                "relevant": [
                    {"camera": "meva-ex", "start_s": 1, "end_s": 2, "start": "2026-10-25T00:00:00Z"}
                ]
            },
            "not both",
        ),
        (
            {
                "relevant": [
                    {
                        "camera": "meva-ex",
                        "start": "2026-10-25T00:00:00",
                        "end": "2026-10-25T00:01:00Z",
                    }
                ]
            },
            "no time zone",
        ),
        ({"relevant": [{"start_s": 1, "end_s": 2}]}, "has no camera"),
        (
            {"relevant": [{"camera": "cam09", "start_s": 1, "end_s": 2}]},
            "outside the camera filter",
        ),
    ],
)
def test_each_way_a_line_can_be_wrong_is_named(over: dict, expected: str) -> None:
    found = check(line(**over))
    assert any(expected in p for p in found), found


def test_a_line_that_is_not_json_is_reported_without_hiding_the_others() -> None:
    found = check("{nope", line(id="q2"), line(id="q2"))
    assert any("not JSON" in p for p in found) and any("q2: id used twice" in p for p in found)


def test_an_implicit_query_must_not_use_the_words_of_its_label() -> None:
    ok = line(kind="implicit", query="someone climbs into the driver's seat", label="enter-vehicle")
    assert check(ok) == []
    bad = line(kind="implicit", query="a person will enter the car", label="enter-vehicle")
    assert any("must not use the words of its label" in p for p in check(bad))
    assert any("needs its label" in p for p in check(line(kind="implicit", label=None)))


@pytest.mark.parametrize(
    "label,text,uses",
    [
        ("stand-up", "someone rises from their seat", False),
        ("stand-up", "everyone stands in the queue", False),  # "stands" is not "stand"
        ("stand-up", "a man will stand still", True),
        ("people-talking", "a pair of pedestrians chatting", False),
        ("people-talking", "TALKING near the gate", True),  # case does not hide it
        ("open-facility-door", "he is going up the stairs", False),  # 'up' is no part of any label
    ],
)
def test_mentions_label_is_whole_words_only(label: str, text: str, uses: bool) -> None:
    assert qs.mentions_label(text, label) is uses


def test_the_summary_counts_the_implicit_share() -> None:
    queries = [
        qs.parse(line(id="a")),
        qs.parse(line(id="b", kind="implicit", query="x y z", label="stand-up")),
    ]
    assert qs.summary(queries) == {
        "queries": 2, "implicit": 1, "implicit_share": 0.5, "with_filters": 2, "relevant_places": 2,
    }  # fmt: skip


def test_the_committed_queries_file_is_valid() -> None:
    path = HERE / "queries.jsonl"
    if not path.exists():
        pytest.skip("queries.jsonl is built by make_queries.py")
    found = qs.problems(qs.load(path))
    assert found == [], found


# ---- metrics ----------------------------------------------------------------------------------

PLACES = [(100.0, 120.0), (300.0, 320.0)]


def test_overlap_below_two_seconds_does_not_reach_a_place() -> None:
    assert mt.reaches((118.0, 128.0), (100.0, 120.0))  # exactly 2 s
    assert not mt.reaches((118.5, 128.0), (100.0, 120.0))


def test_recall_at_k_is_whether_any_of_the_first_k_is_relevant() -> None:
    ranked = [(0.0, 10.0), (50.0, 60.0), (105.0, 115.0)]
    assert [mt.recall_at(ranked, PLACES, k) for k in (1, 2, 3)] == [0.0, 0.0, 1.0]


def test_average_precision_counts_places_not_windows_and_misses_cost_something() -> None:
    # both places reached: at rank 1 (precision 1/1) and rank 3 (precision 2/3)
    ranked = [(100.0, 110.0), (0.0, 10.0), (300.0, 310.0)]
    assert mt.average_precision(ranked, PLACES) == pytest.approx((1 + 2 / 3) / 2)
    # only one place reached: the other counts as zero
    assert mt.average_precision([(100.0, 110.0)], PLACES) == pytest.approx(0.5)
    # two windows on the same place do not count twice
    assert mt.average_precision([(100.0, 110.0), (108.0, 118.0)], PLACES) == pytest.approx(0.5)
    assert mt.average_precision([(0.0, 10.0)], PLACES) == 0.0
    assert mt.average_precision([(100.0, 110.0)], []) == 0.0


def test_average_precision_stops_at_k() -> None:
    ranked = [(0.0, 10.0)] * 10 + [(100.0, 110.0)]
    assert mt.average_precision(ranked, PLACES, k=10) == 0.0
    assert mt.average_precision(ranked, PLACES, k=11) == pytest.approx((1 / 11) / 2)


def test_tiou_is_intersection_over_union_and_a_long_window_cannot_reach_one() -> None:
    assert mt.tiou((0.0, 10.0), (5.0, 15.0)) == pytest.approx(5 / 15)
    assert mt.tiou((0.0, 10.0), (20.0, 30.0)) == 0.0
    assert mt.tiou((100.0, 110.0), (100.0, 105.0)) == pytest.approx(0.5)


def test_tiou_at_looks_at_the_first_result_only() -> None:
    places = [(100.0, 105.0)]
    assert mt.tiou_at([(100.0, 110.0), (100.0, 105.0)], places, 0.5) == 1.0
    assert mt.tiou_at([(100.0, 110.0)], places, 0.6) == 0.0
    assert mt.tiou_at([(0.0, 10.0), (100.0, 105.0)], places, 0.3) == 0.0  # right answer at rank 2
    assert mt.tiou_at([], places, 0.3) == 0.0


def test_query_scores_has_every_metric_the_report_shows() -> None:
    scores = mt.query_scores([(100.0, 110.0)], PLACES)
    assert set(scores) == {"R@1", "R@5", "R@10", "AP@10", "tIoU@0.3", "tIoU@0.5"}
    assert scores["R@1"] == 1.0 and scores["tIoU@0.3"] == pytest.approx(1.0)


def test_percentile_is_nearest_rank() -> None:
    values = list(range(1, 101))
    assert mt.percentile(values, 95) == 95 and mt.percentile(values, 50) == 50
    assert mt.percentile([7], 95) == 7 and math.isnan(mt.percentile([], 95))


def test_stage_latency_reports_the_median_and_p95_of_each_stage_any_query_ran() -> None:
    timings = [
        {"plan": 10.0, "retrieve": 100.0, "total": 110.0},
        {"plan": 30.0, "retrieve": 300.0, "total": 330.0},
        {"plan": 20.0, "retrieve": 200.0, "rerank": 5000.0, "total": 5220.0},
    ]
    lat = mt.stage_latency(timings)
    assert lat["retrieve"] == {"median_ms": 200.0, "p95_ms": 300.0, "n": 3}
    assert lat["rerank"] == {
        "median_ms": 5000.0,
        "p95_ms": 5000.0,
        "n": 1,
    }  # only one query reranked
    assert set(lat) == {"plan", "retrieve", "rerank", "total"}
