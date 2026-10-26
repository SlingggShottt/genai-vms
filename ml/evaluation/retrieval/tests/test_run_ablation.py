"""The ablation runner's own logic with a scripted search (P4-J6): what each configuration asks,
how places meet results, and the summary. No service, no model."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
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


ra = load("run_ablation")
qs = ra.qs

T0 = datetime(2026, 10, 25, 9, 0, 0, tzinfo=UTC).timestamp()


def query(
    qid="q1", kind="explicit", cameras=("meva-ex",), places=((10.0, 20.0),), camera="meva-ex"
):  # noqa: ANN001, ANN201
    return qs.parse(
        json.dumps(
            {
                "id": qid, "query": "a person gets into a car", "kind": kind,
                "label": "enter-vehicle" if kind == "implicit" else None,
                "filters": {"cameras": list(cameras)},
                "relevant": [{"camera": camera, "start_s": a, "end_s": b} for a, b in places],
            }
        )
    )  # fmt: skip


def result(camera: str, start_s: float, length: float = 10.0) -> dict:
    a = datetime.fromtimestamp(T0 + start_s, UTC)
    b = datetime.fromtimestamp(T0 + start_s + length, UTC)
    return {"camera_id": camera, "start_ts": a.isoformat(), "end_ts": b.isoformat()}


def test_each_configuration_asks_for_what_its_name_says() -> None:
    q = query()
    base = ra.payload(q, ra.CONFIGS["embed"], 10)
    assert base == {"query": q.text, "mode": "fast", "jit": False, "top_k": 10}  # no filters
    with_filters = ra.payload(q, ra.CONFIGS["embed+filters"], 10)
    assert with_filters["filters"] == {"cameras": ["meva-ex"]} and with_filters["mode"] == "fast"
    rerank = ra.payload(q, ra.CONFIGS["+rerank"], 10)
    assert rerank["mode"] == "reason" and rerank["jit"] is False and "filters" in rerank
    jit = ra.payload(q, ra.CONFIGS["+jit"], 10)
    assert jit["mode"] == "reason" and jit["jit"] is True


def test_a_query_without_filters_sends_none_even_to_the_configurations_that_use_them() -> None:
    q = query(cameras=())
    assert "filters" not in ra.payload(q, ra.CONFIGS["+rerank"], 10)


def test_places_on_the_recordings_clock_need_an_origin() -> None:
    q = query(places=((10.0, 20.0), (30.0, 40.0)))
    assert ra.places_of(q, T0) == {"meva-ex": [(T0 + 10, T0 + 20), (T0 + 30, T0 + 40)]}
    with pytest.raises(ValueError, match="origin"):
        ra.places_of(q, None)


def test_a_result_reaches_a_place_only_on_its_own_camera() -> None:
    q = query(places=((10.0, 20.0),))
    places = ra.places_of(q, T0)
    same = ra.score({"results": [result("meva-ex", 8.0)]}, places)
    other = ra.score({"results": [result("cam02", 8.0)]}, places)  # same time, another camera
    assert same["R@1"] == 1.0 and same["AP@10"] == 1.0
    assert other["R@1"] == 0.0 and other["R@10"] == 0.0 and other["AP@10"] == 0.0


def test_places_on_two_cameras_are_each_reached_by_their_own() -> None:
    q = qs.parse(
        json.dumps(
            {
                "id": "q1", "query": "a person walks through", "kind": "explicit",
                "relevant": [
                    {"camera": "cam01", "start_s": 10, "end_s": 20},
                    {"camera": "cam02", "start_s": 10, "end_s": 20},
                ],
            }
        )
    )  # fmt: skip
    got = ra.score(
        {"results": [result("cam01", 10.0), result("cam03", 10.0), result("cam02", 10.0)]},
        ra.places_of(q, T0),
    )
    assert got["R@1"] == 1.0
    assert got["AP@10"] == pytest.approx((1 / 1 + 2 / 3) / 2)  # cam01 at rank 1, cam02 at rank 3


async def test_a_run_scores_every_query_and_a_failed_search_is_a_row_not_a_crash() -> None:
    queries = [query("q1"), query("q2"), query("q3", kind="implicit")]
    asked = []

    async def search(body: dict) -> dict:
        asked.append(body)
        if body["query"] and len(asked) == 2:
            raise TimeoutError("the search took too long")
        hit = result("meva-ex", 12.0)
        return {"results": [hit], "timings_ms": {"plan": 10.0, "total": 50.0}, "notes": []}

    out = await ra.run_config(search, "embed", queries, T0, log=lambda _line: None)

    rows = out["rows"]
    assert [r["id"] for r in rows] == ["q1", "q2", "q3"]
    assert rows[1]["error"].startswith("TimeoutError") and rows[1]["R@1"] == 0.0
    assert rows[0]["R@1"] == 1.0 and rows[2]["R@1"] == 1.0
    summary = out["summary"]
    assert summary["n"] == 3 and summary["errors"] == 1
    assert summary["overall"]["R@1"] == pytest.approx(2 / 3, abs=1e-3)  # reported to 3 places
    assert summary["explicit"]["n"] == 2 and summary["implicit"]["n"] == 1
    assert summary["implicit"]["R@1"] == 1.0 and summary["explicit"]["R@1"] == 0.5
    assert summary["latency"]["total"]["n"] == 2  # the failed search reported no timings


def test_the_report_names_every_configuration_and_the_stage_latencies() -> None:
    rows = [
        {"id": "q1", "kind": "explicit", "wall_s": 1.0, "timings_ms": {"plan": 5.0, "total": 9.0},
         "error": None, "notes": [], **{k: 1.0 for k in ra.SCORE_KEYS}},
    ]  # fmt: skip
    report = {
        "finished_at": "2026-10-26 00:00 UTC", "profile": "local", "camera": "meva-ex",
        "n_queries": 1, "implicit": 0,
        "configs": {"embed": {"rows": rows, "summary": ra.summarise(rows)}},
    }  # fmt: skip
    text = ra.markdown(report)
    assert "| embed | 1 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |" in text
    assert "## Latency per stage" in text and "5 / 5" in text
    assert "| embed | explicit | 1 |" in text
