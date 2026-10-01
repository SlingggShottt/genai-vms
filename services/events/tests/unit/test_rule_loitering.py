"""loitering — the same track in a zone for at least `dwell_s` (default 60 s;
design_architecture.md §7.3). Dwell accumulates across 10 s segments."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from events.domain.config import RulesConfig

RULE = "loitering"


def _loiterers(result) -> list:
    return [u for u in result.latest().values() if u.rule_id == RULE]


def _person(make: SimpleNamespace, track: str = "cam01-t1", zones=("yard",), **kw):
    return make.obj(track, zones=zones, **kw)


def test_a_person_staying_for_the_dwell_time_is_loitering(make: SimpleNamespace) -> None:
    zone = make.zone("yard", "generic")
    sequence = make.twins(make.frames(60, [_person(make, conf=0.7)]))

    result = make.run(sequence, [zone])

    (c,) = _loiterers(result)
    assert (c.rule_id, c.event_type, c.severity) == (RULE, "loitering", "medium")
    assert c.zone_name == "yard"
    assert c.track_ids == ["cam01-t1"]
    assert c.start_ts == make.T0
    assert c.end_ts == make.T0 + timedelta(seconds=60)  # reached exactly at the dwell time
    assert c.details["duration_s"] == 60.0
    assert c.rule_score == 0.7


def test_the_candidate_only_appears_once_the_dwell_time_has_been_reached(
    make: SimpleNamespace,
) -> None:
    zone = make.zone("yard", "generic")
    sequence = make.twins(make.frames(60, [_person(make)]))

    result = make.run(sequence, [zone])

    # 60 s of frames fill segments 0-5 fully; the 60.0 s sample is the first in segment 6.
    assert all(batch == [] for batch in result.per_twin[:6])
    assert len(result.per_twin[6]) == 1


def test_just_under_the_dwell_time_is_not_loitering(make: SimpleNamespace) -> None:
    zone = make.zone("yard", "generic")
    sequence = make.twins(make.frames(59.5, [_person(make)]), total_s=100)

    assert _loiterers(make.run(sequence, [zone])) == []


def test_the_candidate_extends_across_segments_with_a_stable_id(make: SimpleNamespace) -> None:
    zone = make.zone("yard", "generic")
    sequence = make.twins(make.frames(95, [_person(make)]), total_s=120)

    result = make.run(sequence, [zone])

    updates = [u for u in result.updates if u.rule_id == RULE]
    assert len({u.id for u in updates}) == 1
    assert [u.end_ts for u in updates] == sorted(u.end_ts for u in updates)
    assert updates[0].start_ts == updates[-1].start_ts == make.T0
    assert updates[-1].end_ts == make.T0 + timedelta(seconds=95)
    # segment ids accumulate in time order, one per segment the stay touched
    assert updates[-1].segment_ids == [t.segment_id for t in sequence[:10]]


def test_the_candidate_stays_open_while_the_person_is_still_there(make: SimpleNamespace) -> None:
    zone = make.zone("yard", "generic")
    # Present until 65 s; the last twin ends at 70 s -> only 5 s quiet, not past the debounce.
    sequence = make.twins(make.frames(65, [_person(make)]))

    (c,) = _loiterers(make.run(sequence, [zone]))

    assert c.status == "open"


def test_the_candidate_closes_once_the_person_has_been_gone_longer_than_the_debounce(
    make: SimpleNamespace,
) -> None:
    zone = make.zone("yard", "generic")
    sequence = make.twins(make.frames(65, [_person(make)]), total_s=90)

    result = make.run(sequence, [zone])

    (c,) = _loiterers(result)
    assert c.status == "closed"
    assert c.end_ts == make.T0 + timedelta(seconds=65)  # last time actually seen
    closing = [u for batch in result.per_twin for u in batch if u.status == "closed"]
    assert len(closing) == 1  # announced once, not on every later quiet segment


def test_different_people_do_not_add_up_to_a_loiterer(make: SimpleNamespace) -> None:
    zone = make.zone("yard", "generic")
    specs = make.frames(40, [_person(make, "cam01-t1")]) + make.frames(
        40, [_person(make, "cam01-t2")], start=40.5
    )

    assert _loiterers(make.run(make.twins(specs, total_s=120), [zone])) == []


def test_leaving_for_longer_than_the_debounce_resets_the_dwell_clock(
    make: SimpleNamespace,
) -> None:
    zone = make.zone("yard", "generic")
    person = [_person(make)]
    specs = make.frames(40, person) + make.frames(40, person, start=50)  # 10 s away

    assert _loiterers(make.run(make.twins(specs, total_s=120), [zone])) == []


def test_a_brief_dropout_does_not_reset_the_dwell_clock(make: SimpleNamespace) -> None:
    zone = make.zone("yard", "generic")
    person = [_person(make)]
    specs = make.frames(40, person) + make.frames(40, person, start=43)  # 3 s dropout

    (c,) = _loiterers(make.run(make.twins(specs, total_s=120), [zone]))

    assert c.start_ts == make.T0
    assert c.end_ts == make.T0 + timedelta(seconds=83)


def test_vehicles_do_not_loiter(make: SimpleNamespace) -> None:
    zone = make.zone("yard", "generic")
    sequence = make.twins(make.frames(120, [_person(make, "cam01-t9", category="car")]))

    assert _loiterers(make.run(sequence, [zone])) == []


def test_it_watches_every_zone_type_by_default(make: SimpleNamespace) -> None:
    for zone_type in ("generic", "restricted", "entrance", "exit"):
        zone = make.zone("yard", zone_type)
        sequence = make.twins(make.frames(60, [_person(make)]))

        assert len(_loiterers(make.run(sequence, [zone]))) == 1, zone_type


def test_zone_types_can_be_restricted_by_configuration(make: SimpleNamespace) -> None:
    exit_zone = make.zone("yard", "exit")
    config = RulesConfig.model_validate(
        {"rules": {RULE: {"params": {"zone_types": ["generic", "entrance"]}}}}
    )
    sequence = make.twins(make.frames(60, [_person(make)]))

    assert _loiterers(make.run(sequence, [exit_zone], config=config)) == []


def test_dwell_time_can_be_overridden_for_one_zone(make: SimpleNamespace) -> None:
    lobby, yard = make.zone("lobby", "generic"), make.zone("yard", "generic")
    config = RulesConfig.model_validate(
        {"overrides": [{"rule": RULE, "zone": "lobby", "params": {"dwell_s": 10}}]}
    )
    in_lobby = make.twins(make.frames(10, [_person(make, zones=("lobby",))]), total_s=40)
    in_yard = make.twins(make.frames(10, [_person(make, zones=("yard",))]), total_s=40)

    assert len(_loiterers(make.run(in_lobby, [lobby, yard], config=config))) == 1
    assert _loiterers(make.run(in_yard, [lobby, yard], config=config)) == []


def test_dwell_time_can_be_overridden_for_one_camera(make: SimpleNamespace) -> None:
    config = RulesConfig.model_validate(
        {"overrides": [{"rule": RULE, "camera": "cam02", "params": {"dwell_s": 10}}]}
    )
    cam1 = make.twins(make.frames(10, [_person(make)]), total_s=40)
    cam2 = make.twins(make.frames(10, [_person(make, "cam02-t1")]), camera_id="cam02", total_s=40)
    yard_cam1, yard_cam2 = (
        make.zone("yard", "generic"),
        make.zone("yard", "generic", camera_id="cam02"),
    )

    assert _loiterers(make.run(cam1, [yard_cam1, yard_cam2], config=config)) == []
    assert (
        len(_loiterers(make.run(cam2, [yard_cam1, yard_cam2], config=config, camera_id="cam02")))
        == 1
    )
