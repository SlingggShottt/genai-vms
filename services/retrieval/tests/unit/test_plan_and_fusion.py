from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from retrieval.domain.fusion import Hit, group_windows
from retrieval.domain.plan import (
    finalize_plan,
    heuristic_plan,
    plan_categories,
    plan_colors,
    resolve_time,
)
from retrieval.domain.rerank import RerankItem, blend

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)


def test_heuristic_plan_reads_category_colour_zone_and_time():
    plan = heuristic_plan(
        "a person in a red top near the service-door in the last hour",
        now=NOW,
        tz=TZ,
        known_zones=["plaza", "service-door"],
    )
    assert plan_categories(plan) == ["person"]
    assert plan_colors(plan) == ["red"]
    assert plan.spatial.zones == ["service-door"]
    assert plan.temporal.start == datetime(2026, 10, 4, 8, 0, tzinfo=UTC)
    assert plan.source == "heuristic"


def test_generic_bag_accepts_every_bag_category():
    plan = heuristic_plan("someone carrying a bag", now=NOW, tz=TZ)
    assert {"backpack", "handbag"} <= set(plan_categories(plan))


def test_time_in_the_text_beats_the_models_time():
    plan = heuristic_plan("person yesterday", now=NOW, tz=TZ)
    wrong = plan.model_copy(
        update={"temporal": plan.temporal.model_copy(update={"start": NOW, "end": NOW})}
    )
    fixed = finalize_plan(wrong, now=NOW, tz=TZ, known_zones=[])
    assert fixed.temporal.end < NOW
    assert resolve_time("nothing about time", NOW, TZ) is None


def test_finalize_drops_event_hints_the_query_never_implied():
    plan = heuristic_plan("person walking", now=NOW, tz=TZ).model_copy(
        update={"event_types_hint": ["loitering"]}
    )
    assert finalize_plan(plan, now=NOW, tz=TZ, known_zones=[]).event_types_hint == []


def _hit(key, cam, t_ms, **kw):
    return Hit(source="frames", key=key, camera_id=cam, start_ms=t_ms, end_ms=t_ms, **kw)


def test_hits_within_the_gap_become_one_window_and_scores_normalise():
    close = [_hit("a", "cam01", 1_000), _hit("b", "cam01", 6_000)]
    far = [_hit("c", "cam01", 60_000), _hit("d", "cam02", 1_000)]
    windows = group_windows([close, far], window_s=10, top_k=10)
    assert len(windows) == 3  # {a,b} on cam01, {c} on cam01, {d} on cam02
    assert windows[0].score == 1.0 and len(windows[0].hits) == 2
    assert all(0 <= w.score <= 1 for w in windows)


def test_rerank_score_scales_and_blend_falls_back_without_a_model_score():
    assert RerankItem(id="c1", score=80).score == 0.8
    assert RerankItem(id="c1", score=7).score == 0.7
    assert blend(0.5, None, 0.6) == 0.5
    assert blend(1.0, 0.0, 0.6) == 0.4
