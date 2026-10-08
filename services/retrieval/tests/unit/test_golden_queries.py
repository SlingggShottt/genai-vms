"""30 golden queries -> plans (P4-D1).

Twenty run the vocabulary-only planner (what a search does when no model answers, and what completes
a model's plan); ten replay what `qwen2.5:3b` really answered to `query_decompose/1.0` (recorded
2026-10-08, `tests/fixtures/query_plans_qwen2.5-3b.json`) through the real `decompose` and
`finalize_plan`. The recordings are the interesting ones: a small model lists every area it was
shown, calls "after dark" a colour and volunteers event types, and the plan must still be safe to
filter with. They found three bugs in this module (zones, event words matched inside other words,
"dark"), each pinned below."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from retrieval.domain.plan import event_hints_in, finalize_plan, heuristic_plan, zones_in
from retrieval.llm_steps import decompose
from vms_common.contracts.search import QuerySpatial
from vms_common.llm.testing import FakeGateway

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=TZ)
ZONES = ["plaza", "service-door", "entrance", "loading-dock", "gate"]


def at(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, 0, tzinfo=TZ)


# (query, categories, colour, zones, event hints, time window or None)
HEURISTIC = [
    ("person in a red jacket", ["person"], "red", [], [], None),
    ("a blue backpack", ["backpack"], "blue", [], [], None),
    ("white car near the gate", ["car"], "white", ["gate"], [], None),
    ("man with a black suitcase", ["person", "suitcase"], "black", [], [], None),
    ("people in the plaza", ["person"], None, ["plaza"], [], None),
    ("someone at the service door", ["person"], None, ["service-door"], [], None),
    ("a truck at the loading dock yesterday", ["truck"], None, ["loading-dock"], [],
     (at(5), at(6))),
    ("loitering near the entrance", [], None, ["entrance"], ["loitering"], None),
    ("an intruder in a restricted area", [], None, [], ["intrusion"], None),
    ("people entering the plaza", ["person"], None, ["plaza"], ["intrusion"], None),
    ("a crowd gathering", ["person"], None, [], ["crowding"], None),
    ("someone running", ["person"], None, [], ["running"], None),
    ("an unattended bag", ["backpack", "handbag"], None, [], ["abandoned_object"], None),
    ("a cyclist today", ["bicycle"], None, [], [], (at(6), NOW)),
    ("person in the last hour", ["person"], None, [], [], (at(6, 11), NOW)),
    ("vehicles on 4 October", ["car"], None, [], [], (at(4), at(5))),
    ("someone on 2026-10-05", ["person"], None, [], [], (at(5), at(6))),
    ("a motorbike at the gate in the past 30 minutes", ["motorcycle"], None, ["gate"], [],
     (datetime(2026, 10, 6, 11, 30, tzinfo=TZ), NOW)),
    ("nothing in particular", [], None, [], [], None),
    ("orange bus", ["bus"], "orange", [], [], None),
]  # fmt: skip


@pytest.mark.parametrize(
    "query,cats,color,zones,hints,window", HEURISTIC, ids=[h[0] for h in HEURISTIC]
)
def test_vocabulary_plan(query, cats, color, zones, hints, window) -> None:
    plan = heuristic_plan(query, now=NOW, tz=TZ, known_zones=ZONES)
    assert [e.category for e in plan.entities] == cats
    colours = [e.attributes.get("color") for e in plan.entities if e.attributes]
    assert colours == ([color] if color else [])
    assert plan.spatial.zones == zones
    assert plan.event_types_hint == hints
    got = (plan.temporal.start, plan.temporal.end) if plan.temporal.start else None
    assert got == window


FIXTURE = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "query_plans_qwen2.5-3b.json").read_text()
)["replies"]

# query -> (categories the plan must contain, colour of the first entity, zones, hints, window)
RECORDED = {
    "a man in a red jacket loitering near the service door in the last hour":
        (["person"], "red", ["service-door"], ["loitering"], (at(6, 11), NOW)),
    "someone leaving a bag unattended in the plaza":
        (["person", "backpack"], None, ["plaza"], ["abandoned_object"], None),
    "people running toward the exit": (["person"], None, [], ["running"], None),
    "a crowd gathering at the entrance this morning":
        (["person"], None, ["entrance"], ["crowding"], (at(6), NOW)),
    "white van parked near the loading dock yesterday":
        (["car"], "white", ["loading-dock"], [], (at(5), at(6))),
    "person carrying a large box": (["person"], None, [], [], None),
    "anyone climbing the fence after dark": (["person"], None, [], [], None),
    "a cyclist on 4 October": (["bicycle"], None, [], [], (at(4), at(5))),
    "two people arguing near the gate": (["person"], None, ["gate"], [], None),
    "blue backpack left on a bench": (["backpack"], "blue", [], [], None),
}  # fmt: skip


@pytest.mark.parametrize("query", list(RECORDED), ids=[q[:40] for q in RECORDED])
async def test_what_a_small_model_really_answered_becomes_a_safe_plan(query: str) -> None:
    cats, color, zones, hints, window = RECORDED[query]
    gateway = FakeGateway({"query_decompose": [FIXTURE[query]]})
    draft = await decompose(gateway, query, now=NOW, tz=TZ, zones=ZONES)
    plan = finalize_plan(draft, now=NOW, tz=TZ, known_zones=ZONES)

    found = [e.category for e in plan.entities]
    assert set(cats) <= set(found)
    assert set(found) <= {"person", "backpack", "handbag", "suitcase", "car", "bicycle",
                          "motorcycle", "bus", "truck"}  # detector categories only  # fmt: skip
    assert plan.entities[0].attributes.get("color") == color
    assert plan.spatial.zones == zones
    assert plan.event_types_hint == hints
    got = (plan.temporal.start, plan.temporal.end) if plan.temporal.start else None
    assert got == window
    assert 1 <= len(plan.visual_queries) <= 3 and plan.source == "llm"


# ---- the three bugs the recordings found -----------------------------------------------------


def test_a_model_that_lists_every_area_it_was_shown_has_not_chosen_any() -> None:
    draft = FIXTURE["someone leaving a bag unattended in the plaza"]
    assert '"plaza"' in draft and '"gate"' in draft  # the recorded reply names several areas
    plan = finalize_plan(
        heuristic_plan("people running toward the exit", now=NOW, tz=TZ, known_zones=ZONES)
        .model_copy(update={"spatial": QuerySpatial(zones=list(ZONES))}),
        now=NOW, tz=TZ, known_zones=ZONES,
    )  # fmt: skip
    assert plan.spatial.zones == []  # nothing in the text names an area


def test_one_or_two_areas_from_the_model_are_kept() -> None:
    base = heuristic_plan("someone near the door", now=NOW, tz=TZ, known_zones=ZONES)
    chosen = base.model_copy(update={"spatial": QuerySpatial(zones=["service-door"])})
    assert finalize_plan(chosen, now=NOW, tz=TZ, known_zones=ZONES).spatial.zones == [
        "service-door"
    ]


def test_the_area_the_text_names_beats_the_models_guesses() -> None:
    base = heuristic_plan("a crowd at the entrance", now=NOW, tz=TZ, known_zones=ZONES)
    guessed = base.model_copy(update={"spatial": QuerySpatial(zones=["entrance", "service-door"])})
    got = finalize_plan(guessed, now=NOW, tz=TZ, known_zones=ZONES)
    assert got.spatial.zones == ["entrance"]


@pytest.mark.parametrize(
    "text,hints",
    [
        ("a crowd gathering at the entrance", ["crowding"]),  # 'ran' is inside 'entrance'
        ("an orange car", []),  # ...and inside 'orange'
        ("a strange person", []),
        ("he ran away", ["running"]),
        ("intrusions overnight", ["intrusion"]),  # plurals still work
        ("someone enters the area", ["intrusion"]),
        ("a random person", []),
        ("people waiting in a group", ["loitering", "crowding"]),
    ],
)
def test_event_words_are_matched_as_words(text: str, hints: list[str]) -> None:
    assert event_hints_in(text) == hints


@pytest.mark.parametrize(
    "text,colours",
    [
        ("a person after dark", []),  # a time of day
        ("movement before dark", []),
        ("someone in the dark", []),
        ("a person during the dark hours", []),
        ("movement in dark conditions", []),
        ("a person in a dark jacket", ["black"]),  # a colour
        ("dark clothes near the gate", ["black"]),
    ],
)
def test_dark_is_a_colour_only_when_it_describes_something(text: str, colours: list[str]) -> None:
    from retrieval.domain.plan import colors_in

    assert colors_in(text) == colours


def test_an_area_is_matched_as_a_word() -> None:
    assert zones_in("investigate the gateway", ZONES) == []
    assert zones_in("someone at the gate.", ZONES) == ["gate"]
    assert zones_in("the service door and the loading dock", ZONES) == [
        "service-door",
        "loading-dock",
    ]
