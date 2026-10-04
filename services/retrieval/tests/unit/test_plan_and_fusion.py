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


def test_router_picks_the_lookup_a_clear_question_means():
    from retrieval.assistant.router import route

    cams = ["cam01", "cam-2"]
    assert route("How many people were on cam01 at the busiest time today?", cams) == (
        "count_objects",
        {"category": "person", "when": "today", "group_by": "hour", "camera": "cam01"},
    )
    assert route("Were there any serious incidents today?", cams)[0] == "list_incidents"
    assert route("What happened on cam01 in the last 2 hours?", cams) == (
        "list_events",
        {"when": "last 2 hours", "limit": 10, "camera": "cam01"},
    )
    assert route("Find a man carrying a red bag", cams)[0] == "search_footage"
    assert route("Show me the daily report for yesterday", cams) == (
        "get_daily_report",
        {"date": "yesterday"},
    )
    assert route("hello there", cams) is None


def test_lead_sentence_is_the_tools_own_header_without_tags():
    from retrieval.assistant.router import lead_sentence

    got = lead_sentence(
        "list_incidents", "5 incident report(s) (severity: 5 HIGH), newest first:\n[I:ab] x"
    )
    assert got == "5 incident report(s) (severity: 5 HIGH)."
    assert lead_sentence("list_events", "No verified events in that period.") == (
        "No verified events in that period."
    )


def test_a_repeated_lead_is_stripped_from_the_models_opening():
    from retrieval.assistant.agent import strip_repeat

    lead = "5 incident report(s) (severity: 5 HIGH)."
    assert strip_repeat(
        'Answer: "5 incident report(s) (severity: 5 HIGH). They were at noon."', lead
    ) == ("They were at noon.")
    assert strip_repeat("They were at noon.", lead) == "They were at noon."


def test_evidence_only_resolves_tags_it_handed_out():
    from retrieval.assistant.evidence import Evidence

    ev = Evidence()
    tag = ev.event(
        "30b6f125-67c9-5eee-93ad-73d79e17268e", "intrusion on cam01", camera="cam01", ts=None
    )
    valid, unknown = ev.resolve(f"One intrusion {tag} and a made-up one [E:deadbeef].")
    assert [c.ref[:8] for c in valid] == ["30b6f125"] and unknown == ["E:deadbeef"]


def test_rle_round_trips_any_mask():
    import numpy as np
    from retrieval.adapters.grounding import rle_decode, rle_encode

    rng = np.random.default_rng(0)
    for mask in (
        rng.random((7, 11)) > 0.5,
        np.zeros((4, 4), dtype=bool),
        np.ones((3, 5), dtype=bool),
    ):
        assert (rle_decode(rle_encode(mask)) == mask).all()
