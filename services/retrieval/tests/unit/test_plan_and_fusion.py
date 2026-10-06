from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from retrieval.domain.fusion import Hit, group_windows
from retrieval.domain.plan import (
    finalize_plan,
    find_date,
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


TODAY = date(2026, 10, 4)


def test_a_date_written_the_way_people_write_it_is_found():
    for text in (
        "what happened on 2026-10-04?",
        "what happened on 4 October?",
        "what happened on October 4th",
        "what happened on the 4th of October",
        "what happened on 4 oct",
    ):
        assert find_date(text, TODAY) == date(2026, 10, 4), text
    assert find_date("on 21st of november 2025", TODAY) == date(2025, 11, 21)
    assert find_date("on 1 sept", TODAY) == date(2026, 9, 1)


def test_a_day_without_a_year_is_the_latest_such_day_not_in_the_future():
    assert find_date("on 20 November", TODAY) == date(2025, 11, 20)  # not yet this year
    assert find_date("on 4 October", TODAY) == date(2026, 10, 4)  # today counts
    assert find_date("on 5 October", TODAY) == date(2025, 10, 5)  # tomorrow does not


def test_things_that_are_not_dates_are_not_dates():
    for text in (
        "someone may enter the yard",
        "31 February",
        "2026-13-40",
        "how many people at 4 pm",
        "camera 4 and camera 10",
    ):
        assert find_date(text, TODAY) is None, text


def test_a_named_day_is_the_whole_of_that_day_on_the_sites_clock():
    # Asia/Kolkata is UTC+5:30: 4 October there is 18:30 UTC on the 3rd to 18:30 UTC on the 4th
    start, end = resolve_time("what happened on cam01 on 4 October", NOW, TZ)
    assert (start, end) == (
        datetime(2026, 10, 3, 18, 30, tzinfo=UTC),
        datetime(2026, 10, 4, 18, 30, tzinfo=UTC),
    )
    assert resolve_time("2026-10-04", NOW, TZ) == (start, end)
    # a named day wins over a loose phrase in the same question
    assert resolve_time("yesterday, I mean 1 October", NOW, TZ)[0] == datetime(
        2026, 9, 30, 18, 30, tzinfo=UTC
    )


def test_plural_object_words_are_recognised():
    from retrieval.domain.plan import categories_in

    assert categories_in("how many trucks and bags") == ["backpack", "handbag", "truck"]
    assert categories_in("two buses and some lorries") == ["bus", "truck"]
    assert categories_in("three cars, a bicycle and two bikes") == ["car", "bicycle"]
    assert categories_in("nobody here but gases") == []  # "gases" -> "gas", "gase": no category


def test_how_many_events_is_a_list_not_a_person_count():
    from retrieval.assistant.router import route

    cams = ["cam01", "bus-g340"]
    got = route("How many intrusion events were verified on cam01 on 4 October?", cams, TODAY)
    assert got == (
        "list_events",
        {"when": "2026-10-04", "limit": 10, "type": "intrusion", "camera": "cam01"},
    )
    # "bus-g340" is a camera, not a question about buses
    assert route("How many alerts were there on bus-g340?", cams, TODAY)[0] == "list_events"
    assert route("How many buses were on bus-g340?", cams, TODAY)[1]["category"] == "bus"
    assert route("How many incidents on cam01 yesterday?", cams, TODAY)[0] == "list_incidents"
    # an object in the question keeps it a count of things seen
    assert route("How many people were on cam01 on 4 October?", cams, TODAY) == (
        "count_objects",
        {"category": "person", "when": "2026-10-04", "group_by": "none", "camera": "cam01"},
    )
    assert (
        route("How many people entered during the intrusion on cam01?", cams, TODAY)[0]
        == "count_objects"
    )


def test_the_router_carries_the_day_and_the_camera_into_every_lookup_that_takes_them():
    from retrieval.assistant.router import route

    cams = ["cam01", "bus-g340"]
    assert route("What happened on bus-g340 on October 4?", cams, TODAY) == (
        "list_events",
        {"when": "2026-10-04", "limit": 10, "camera": "bus-g340"},
    )
    assert route("Were there any serious incidents on bus-g340?", cams, TODAY) == (
        "list_incidents",
        {"when": "last 24 hours", "limit": 5, "camera": "bus-g340"},
    )
    assert route("Give me the timeline of events on cam01 on 2026-10-04.", cams, TODAY) == (
        "get_timeline",
        {"when": "2026-10-04", "cameras": ["cam01"]},
    )
    assert route("Show the daily report for 2026-10-02.", cams, TODAY) == (
        "get_daily_report",
        {"date": "2026-10-02"},
    )
    assert route("Show the daily report for yesterday.", cams, TODAY) == (
        "get_daily_report",
        {"date": "yesterday"},
    )


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


def test_only_real_questions_are_sent_to_the_vision_model():
    from retrieval.jit import askable, question_hash

    got = askable(
        ["Is the bag blue?", "No information about the colour of the bag", "ok?", "Does he run?"]
    )
    assert got == ["Is the bag blue?", "Does he run?"]
    assert question_hash("Is the bag blue?") == question_hash("is the BAG blue")
