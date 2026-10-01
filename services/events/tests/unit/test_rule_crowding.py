"""crowding — more than `max_persons` (8) in a zone for at least `duration_s`
(20 s; design_architecture.md §7.3). A zone-wide condition: one crowd, one
candidate, however individual tracks come and go."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from events.domain.config import RulesConfig

RULE = "crowding"


def _crowds(result) -> list:
    return [u for u in result.latest().values() if u.rule_id == RULE]


def _people(make: SimpleNamespace, count: int, *, first: int = 1, zones=("plaza",), **kw) -> list:
    return [make.obj(f"cam01-t{i}", zones=zones, **kw) for i in range(first, first + count)]


def test_more_than_the_limit_for_the_duration_is_crowding(make: SimpleNamespace) -> None:
    zone = make.zone("plaza", "generic")
    sequence = make.twins(make.frames(20, _people(make, 9)))

    (c,) = _crowds(make.run(sequence, [zone]))

    assert (c.rule_id, c.event_type, c.severity) == (RULE, "crowding", "medium")
    assert c.zone_name == "plaza"
    assert c.start_ts == make.T0
    assert c.end_ts == make.T0 + timedelta(seconds=20)
    assert c.details["peak_count"] == 9
    assert c.details["duration_s"] == 20.0
    assert len(c.track_ids) == 9


def test_exactly_the_limit_is_not_crowding(make: SimpleNamespace) -> None:
    zone = make.zone("plaza", "generic")
    sequence = make.twins(make.frames(60, _people(make, 8)), total_s=80)

    assert _crowds(make.run(sequence, [zone])) == []


def test_a_crowd_that_disperses_before_the_duration_is_not_reported(make: SimpleNamespace) -> None:
    zone = make.zone("plaza", "generic")
    sequence = make.twins(make.frames(19.5, _people(make, 12)), total_s=60)

    assert _crowds(make.run(sequence, [zone])) == []


def test_the_candidate_extends_while_the_crowd_stays_and_closes_when_it_goes(
    make: SimpleNamespace,
) -> None:
    zone = make.zone("plaza", "generic")
    sequence = make.twins(make.frames(45, _people(make, 10)), total_s=70)

    result = make.run(sequence, [zone])

    updates = [u for u in result.updates if u.rule_id == RULE]
    assert len({u.id for u in updates}) == 1
    assert updates[-1].end_ts == make.T0 + timedelta(seconds=45)
    assert updates[-1].status == "closed"
    assert sum(1 for u in updates if u.status == "closed") == 1


def test_one_frame_dip_below_the_limit_does_not_split_the_crowd(make: SimpleNamespace) -> None:
    zone = make.zone("plaza", "generic")
    crowd = _people(make, 10)
    specs = (
        make.frames(10, crowd)
        + [(10.5, _people(make, 6))]  # one sample with only 6 people
        + make.frames(10, crowd, start=11.0)
    )

    (c,) = _crowds(make.run(make.twins(specs, total_s=40), [zone]))

    assert c.start_ts == make.T0
    assert c.end_ts == make.T0 + timedelta(seconds=21)


def test_a_long_dip_ends_the_crowd_and_a_new_one_needs_the_full_duration(
    make: SimpleNamespace,
) -> None:
    zone = make.zone("plaza", "generic")
    crowd = _people(make, 10)
    specs = make.frames(25, crowd) + make.frames(10, crowd, start=40)  # 15 s gap, then only 10 s

    candidates = _crowds(make.run(make.twins(specs, total_s=80), [zone]))

    assert len(candidates) == 1  # the second 10 s burst is too short to count
    assert candidates[0].end_ts == make.T0 + timedelta(seconds=25)


def test_people_swapping_in_and_out_is_still_one_crowd(make: SimpleNamespace) -> None:
    zone = make.zone("plaza", "generic")
    first_wave = make.frames(15, _people(make, 9, first=1))
    second_wave = make.frames(15, _people(make, 9, first=10), start=15.5)  # all new faces

    (c,) = _crowds(make.run(make.twins(first_wave + second_wave, total_s=50), [zone]))

    assert len(c.track_ids) == 18  # everyone who was part of it
    assert c.details["peak_count"] == 9


def test_the_score_grows_with_the_headcount_up_to_one(make: SimpleNamespace) -> None:
    zone = make.zone("plaza", "generic")

    modest = _crowds(make.run(make.twins(make.frames(20, _people(make, 9))), [zone]))[0]
    packed = _crowds(make.run(make.twins(make.frames(20, _people(make, 40))), [zone]))[0]

    assert 0.5 < modest.rule_score < packed.rule_score
    assert packed.rule_score == 1.0


def test_only_people_inside_the_zone_are_counted(make: SimpleNamespace) -> None:
    zone = make.zone("plaza", "generic")
    inside, outside = _people(make, 5), _people(make, 5, first=20, zones=())
    sequence = make.twins(make.frames(40, inside + outside), total_s=60)

    assert _crowds(make.run(sequence, [zone])) == []


def test_vehicles_are_not_counted_as_people(make: SimpleNamespace) -> None:
    zone = make.zone("plaza", "generic")
    mixed = _people(make, 5) + _people(make, 5, first=30, category="car")
    sequence = make.twins(make.frames(40, mixed), total_s=60)

    assert _crowds(make.run(sequence, [zone])) == []


def test_the_same_track_is_counted_once(make: SimpleNamespace) -> None:
    zone = make.zone("plaza", "generic")
    duplicated = _people(make, 5) * 2  # ten detections but five distinct track ids
    sequence = make.twins(make.frames(40, duplicated), total_s=60)

    assert _crowds(make.run(sequence, [zone])) == []


def test_each_zone_is_counted_separately(make: SimpleNamespace) -> None:
    plaza, gate = make.zone("plaza", "generic"), make.zone("gate", "entrance")
    both = _people(make, 9, zones=("plaza",)) + _people(make, 9, first=50, zones=("gate",))
    sequence = make.twins(make.frames(20, both))

    candidates = _crowds(make.run(sequence, [plaza, gate]))

    assert sorted(c.zone_name for c in candidates) == ["gate", "plaza"]


def test_the_limit_and_duration_can_be_overridden_for_one_zone(make: SimpleNamespace) -> None:
    lobby = make.zone("lobby", "generic")
    config = RulesConfig.model_validate(
        {
            "overrides": [
                {"rule": RULE, "zone": "lobby", "params": {"max_persons": 3, "duration_s": 5}}
            ]
        }
    )
    sequence = make.twins(make.frames(5, _people(make, 4, zones=("lobby",))), total_s=30)

    (c,) = _crowds(make.run(sequence, [lobby], config=config))

    assert c.details["peak_count"] == 4


def test_it_can_be_limited_to_certain_zone_types(make: SimpleNamespace) -> None:
    zone = make.zone("plaza", "exit")
    config = RulesConfig.model_validate({"rules": {RULE: {"params": {"zone_types": ["generic"]}}}})
    sequence = make.twins(make.frames(20, _people(make, 9)))

    assert _crowds(make.run(sequence, [zone], config=config)) == []
