"""intrusion.restricted — a person or vehicle in a `restricted` zone, 2+ frames
(design_architecture.md §7.3). Synthetic twin sequences, positive + negative."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from events.domain.config import RulesConfig

RULE = "intrusion.restricted"


def _only(result) -> list:
    return [u for u in result.latest().values() if u.rule_id == RULE]


def test_a_person_in_a_restricted_zone_raises_a_high_severity_intrusion(
    make: SimpleNamespace,
) -> None:
    zone = make.zone("yard", "restricted")
    sequence = make.twins(make.frames(2, [make.obj("cam01-t7", conf=0.8)]))

    candidates = _only(make.run(sequence, [zone]))

    assert len(candidates) == 1
    c = candidates[0]
    assert (c.rule_id, c.event_type, c.severity) == (RULE, "intrusion", "high")
    assert (c.camera_id, c.site_id) == ("cam01", "rvce-campus")
    assert (c.zone_id, c.zone_name) == ("zone-yard", "yard")
    assert c.track_ids == ["cam01-t7"]
    assert c.segment_ids == [sequence[0].segment_id]
    assert c.start_ts == make.T0
    assert c.end_ts == make.T0 + timedelta(seconds=2)
    assert c.rule_score == 0.8


def test_a_vehicle_in_a_restricted_zone_is_an_intrusion_too(make: SimpleNamespace) -> None:
    zone = make.zone("yard", "restricted")
    sequence = make.twins(make.frames(2, [make.obj("cam01-t3", "car")]))

    candidates = _only(make.run(sequence, [zone]))

    assert [c.track_ids for c in candidates] == [["cam01-t3"]]


def test_a_single_frame_is_not_enough(make: SimpleNamespace) -> None:
    zone = make.zone("yard", "restricted")
    sequence = make.twins([(0.0, [make.obj("cam01-t1")])])

    assert _only(make.run(sequence, [zone])) == []


def test_min_frames_is_configurable(make: SimpleNamespace) -> None:
    zone = make.zone("yard", "restricted")
    sequence = make.twins([(0.0, [make.obj("cam01-t1")])])
    config = RulesConfig.model_validate({"rules": {RULE: {"params": {"min_frames": 1}}}})

    assert len(_only(make.run(sequence, [zone], config=config))) == 1


def test_presence_in_a_generic_or_entrance_zone_is_not_an_intrusion(make: SimpleNamespace) -> None:
    for zone_type in ("generic", "entrance", "exit"):
        zone = make.zone("yard", zone_type)
        sequence = make.twins(make.frames(5, [make.obj("cam01-t1")]))

        assert _only(make.run(sequence, [zone])) == [], zone_type


def test_categories_outside_the_configured_list_are_ignored(make: SimpleNamespace) -> None:
    zone = make.zone("yard", "restricted")
    sequence = make.twins(make.frames(5, [make.obj("cam01-t1", "backpack")]))

    assert _only(make.run(sequence, [zone])) == []


def test_an_object_not_standing_in_the_zone_is_ignored(make: SimpleNamespace) -> None:
    zone = make.zone("yard", "restricted")
    sequence = make.twins(make.frames(5, [make.obj("cam01-t1", zones=())]))

    assert _only(make.run(sequence, [zone])) == []


def test_a_zone_name_with_no_matching_zone_is_ignored(make: SimpleNamespace) -> None:
    sequence = make.twins(make.frames(5, [make.obj("cam01-t1", zones=("deleted-zone",))]))

    assert _only(make.run(sequence, [make.zone("yard", "restricted")])) == []


def test_another_cameras_zone_of_the_same_name_does_not_count(make: SimpleNamespace) -> None:
    other_camera_zone = make.zone("yard", "restricted", camera_id="cam02")
    sequence = make.twins(make.frames(5, [make.obj("cam01-t1")]))

    assert _only(make.run(sequence, [other_camera_zone])) == []


def test_two_people_are_two_candidates(make: SimpleNamespace) -> None:
    zone = make.zone("yard", "restricted")
    people = [make.obj("cam01-t1"), make.obj("cam01-t2")]
    sequence = make.twins(make.frames(3, people))

    candidates = _only(make.run(sequence, [zone]))

    assert sorted(c.track_ids[0] for c in candidates) == ["cam01-t1", "cam01-t2"]


def test_a_short_gap_is_debounced_into_one_candidate(make: SimpleNamespace) -> None:
    zone = make.zone("yard", "restricted")
    person = [make.obj("cam01-t1")]
    # 2 s present, 4 s gone (< the 5 s debounce), 2 s present again.
    specs = make.frames(2, person) + make.frames(2, person, start=6.0)
    sequence = make.twins(specs, total_s=20)

    candidates = _only(make.run(sequence, [zone]))

    assert len(candidates) == 1
    assert candidates[0].end_ts == make.T0 + timedelta(seconds=8)


def test_a_long_gap_starts_a_new_candidate(make: SimpleNamespace) -> None:
    zone = make.zone("yard", "restricted")
    person = [make.obj("cam01-t1")]
    # 2 s present, 8 s gone (> the 5 s debounce), 2 s present again.
    specs = make.frames(2, person) + make.frames(2, person, start=10.0)
    sequence = make.twins(specs, total_s=30)

    candidates = sorted(_only(make.run(sequence, [zone])), key=lambda c: c.start_ts)

    assert len(candidates) == 2
    assert candidates[0].start_ts == make.T0
    assert candidates[1].start_ts == make.T0 + timedelta(seconds=10)
    assert candidates[0].id != candidates[1].id
    assert all(c.status == "closed" for c in candidates)
