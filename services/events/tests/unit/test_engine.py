"""The engine's stateful behaviour: replay/restart safety, purity, closing and
config changes (P3-D1 AC: sliding state, debounce/extension). Pure."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from events.domain.config import RulesConfig
from events.domain.engine import process_twin
from events.domain.state import CameraState


def _loiter_sequence(make: SimpleNamespace, seconds: float = 95, total_s: float = 120) -> list:
    person = [make.obj("cam01-t1", zones=("yard",))]
    return make.twins(make.frames(seconds, person), total_s=total_s)


def _yard(make: SimpleNamespace):
    return make.zone("yard", "generic")


def _process(make: SimpleNamespace, state, twin, zones, config=None):
    return process_twin(state, twin, zones=zones, config=config or RulesConfig(), site_tz=make.IST)


# --- replay, ordering and purity ------------------------------------------


def test_replaying_a_twin_that_was_already_applied_changes_nothing(make: SimpleNamespace) -> None:
    sequence = _loiter_sequence(make)
    result = make.run(sequence[:8], [_yard(make)])

    replay = _process(make, result.state, sequence[7], [_yard(make)])

    assert replay.skipped is True
    assert replay.updates == []
    assert replay.state == result.state


def test_an_older_twin_than_the_state_has_seen_is_skipped(make: SimpleNamespace) -> None:
    sequence = _loiter_sequence(make)
    result = make.run(sequence[:8], [_yard(make)])

    late = _process(make, result.state, sequence[2], [_yard(make)])

    assert (late.skipped, late.updates) == (True, [])


def test_process_twin_does_not_mutate_the_state_it_is_given(make: SimpleNamespace) -> None:
    sequence = _loiter_sequence(make)
    result = make.run(sequence[:5], [_yard(make)])
    before = result.state.model_dump_json()

    outcome = _process(make, result.state, sequence[5], [_yard(make)])

    assert result.state.model_dump_json() == before
    assert outcome.state is not result.state
    assert outcome.state.last_segment_end > result.state.last_segment_end


def test_a_twin_for_another_camera_is_refused(make: SimpleNamespace) -> None:
    twin = make.twins(make.frames(1, [make.obj("cam02-t1")]), camera_id="cam02")[0]

    with pytest.raises(ValueError, match="cam01.*cam02"):
        _process(make, CameraState(camera_id="cam01"), twin, [])


def test_the_same_input_always_yields_identical_candidates(make: SimpleNamespace) -> None:
    sequence = _loiter_sequence(make)

    first = make.run(sequence, [_yard(make)])
    second = make.run(sequence, [_yard(make)])

    assert first.updates == second.updates
    assert len(first.updates) > 0


def test_a_crash_between_the_database_write_and_the_state_checkpoint_is_harmless(
    make: SimpleNamespace,
) -> None:
    # The worker writes candidates, then saves state. If it dies in between, the twin is
    # redelivered against the OLD state and must produce exactly the same updates.
    sequence = _loiter_sequence(make)
    before = make.run(sequence[:7], [_yard(make)])

    attempt_1 = _process(make, before.state, sequence[7], [_yard(make)])
    attempt_2 = _process(make, before.state, sequence[7], [_yard(make)])

    assert attempt_1.updates == attempt_2.updates
    assert attempt_1.state == attempt_2.state
    assert len(attempt_1.updates) == 1


def test_state_survives_being_saved_and_loaded_mid_stay(make: SimpleNamespace) -> None:
    sequence = _loiter_sequence(make)
    uninterrupted = make.run(sequence, [_yard(make)])

    first_half = make.run(sequence[:4], [_yard(make)])
    reloaded = CameraState.model_validate_json(first_half.state.model_dump_json())  # "restart"
    second_half = make.run(sequence[4:], [_yard(make)], state=reloaded)

    assert second_half.latest() == uninterrupted.latest()
    assert second_half.state == uninterrupted.state


def test_without_the_saved_state_a_restart_forgets_the_stay_so_far(make: SimpleNamespace) -> None:
    # Documents what the Redis checkpoint is for: a cold start mid-stay would restart dwell.
    sequence = _loiter_sequence(make, seconds=65)

    cold_start = make.run(sequence[4:], [_yard(make)])  # only the last ~35 s of a 65 s stay

    assert [u for u in cold_start.updates if u.rule_id == "loitering"] == []


# --- episodes: arming, extending, closing ---------------------------------


def test_the_state_tracks_the_open_episode_with_its_dwell(make: SimpleNamespace) -> None:
    sequence = _loiter_sequence(make, seconds=65, total_s=70)

    result = make.run(sequence, [_yard(make)])

    (episode,) = result.state.episodes.values()
    assert episode.rule_id == "loitering"
    assert (episode.zone_name, episode.hit_key) == ("yard", "cam01-t1")
    assert episode.duration_s == 65.0
    assert episode.candidate_id is not None


def test_episodes_that_never_reach_their_threshold_leave_no_trace(make: SimpleNamespace) -> None:
    zone = make.zone("yard", "restricted")
    sequence = make.twins([(0.0, [make.obj("cam01-t1")])], total_s=30)  # one frame only

    result = make.run(sequence, [zone])

    assert result.updates == []
    assert result.state.episodes == {}


def test_a_quiet_segment_with_no_detections_still_closes_a_finished_episode(
    make: SimpleNamespace,
) -> None:
    zone = make.zone("yard", "restricted")
    person = [make.obj("cam01-t1")]
    sequence = make.twins(make.frames(3, person), total_s=40)  # 3 s present, then quiet twins

    result = make.run(sequence, [zone])

    assert [len(batch) for batch in result.per_twin] == [1, 0, 0, 0]
    assert result.per_twin[0][0].status == "closed"  # first twin ends 10 s after the last hit
    assert result.state.episodes == {}


def test_a_closed_candidate_is_never_reopened_by_later_activity(make: SimpleNamespace) -> None:
    zone = make.zone("yard", "restricted")
    person = [make.obj("cam01-t1")]
    specs = make.frames(3, person) + make.frames(3, person, start=30)

    result = make.run(make.twins(specs, total_s=60), [zone])

    first, second = sorted(result.latest().values(), key=lambda u: u.start_ts)
    assert first.status == second.status == "closed"
    assert first.id != second.id
    assert first.end_ts == make.T0 + timedelta(seconds=3)


def test_a_gap_longer_than_the_debounce_inside_one_segment_splits_the_episode(
    make: SimpleNamespace,
) -> None:
    # Both bursts sit in the same 10 s twin (0-1 s and 7-8 s, a 6 s gap > the 5 s debounce),
    # so nothing closes the first episode at a segment boundary: the engine must notice the gap
    # itself when the second burst arrives.
    zone = make.zone("yard", "restricted")
    person = [make.obj("cam01-t1")]
    specs = make.frames(1, person) + make.frames(1, person, start=7.0)

    result = make.run(make.twins(specs, total_s=30), [zone])

    first, second = sorted(result.latest().values(), key=lambda u: u.start_ts)
    assert (first.start_ts, first.end_ts) == (make.T0, make.T0 + timedelta(seconds=1))
    assert (second.start_ts, second.end_ts) == (
        make.T0 + timedelta(seconds=7),
        make.T0 + timedelta(seconds=8),
    )
    assert first.id != second.id


def test_a_gap_within_the_debounce_inside_one_segment_keeps_one_episode(
    make: SimpleNamespace,
) -> None:
    zone = make.zone("yard", "restricted")
    person = [make.obj("cam01-t1")]
    specs = make.frames(1, person) + make.frames(1, person, start=5.5)  # 4.5 s gap <= 5 s

    (candidate,) = make.run(make.twins(specs, total_s=30), [zone]).latest().values()

    assert (candidate.start_ts, candidate.end_ts) == (make.T0, make.T0 + timedelta(seconds=6.5))


def test_two_rules_can_fire_on_the_same_person(make: SimpleNamespace) -> None:
    zone = make.zone("yard", "restricted")
    person = [make.obj("cam01-t1")]
    sequence = make.twins(make.frames(60, person), total_s=80)

    rules = {u.rule_id for u in make.run(sequence, [zone]).latest().values()}

    assert rules == {"intrusion.restricted", "loitering"}


def test_updates_come_out_in_a_deterministic_order(make: SimpleNamespace) -> None:
    zone = make.zone("yard", "restricted")
    people = [make.obj("cam01-t1"), make.obj("cam01-t2")]
    sequence = make.twins(make.frames(3, people), total_s=20)

    first = make.run(sequence, [zone]).per_twin[0]
    second = make.run(sequence, [zone]).per_twin[0]

    assert [u.id for u in first] == [u.id for u in second]
    assert len(first) == 2


# --- zones and cameras ------------------------------------------------------


def test_objects_with_no_zone_or_an_unknown_zone_never_raise_anything(
    make: SimpleNamespace,
) -> None:
    loose = [make.obj("cam01-t1", zones=()), make.obj("cam01-t2", zones=("ghost-zone",))]
    sequence = make.twins(make.frames(120, loose))

    result = make.run(sequence, [make.zone("yard", "restricted")])

    assert result.updates == []
    assert result.state.episodes == {}


def test_a_camera_with_no_zones_raises_nothing(make: SimpleNamespace) -> None:
    sequence = make.twins(make.frames(120, [make.obj("cam01-t1", zones=("yard",))]))

    assert make.run(sequence, []).updates == []


def test_cameras_keep_independent_state_and_their_own_zones(make: SimpleNamespace) -> None:
    zones = [
        make.zone("yard", "restricted", camera_id="cam01"),
        make.zone("yard", "generic", camera_id="cam02"),  # same name, different type
    ]
    cam1 = make.twins(make.frames(3, [make.obj("cam01-t1")]), camera_id="cam01", total_s=20)
    cam2 = make.twins(make.frames(3, [make.obj("cam02-t1")]), camera_id="cam02", total_s=20)

    on_cam1 = make.run(cam1, zones, camera_id="cam01")
    on_cam2 = make.run(cam2, zones, camera_id="cam02")

    assert {u.rule_id for u in on_cam1.updates} == {"intrusion.restricted"}
    assert on_cam2.updates == []  # cam02's "yard" is a generic zone


# --- configuration changes -------------------------------------------------


def test_switching_a_rule_off_closes_its_open_candidates(make: SimpleNamespace) -> None:
    sequence = _loiter_sequence(make, seconds=95, total_s=120)
    running = make.run(sequence[:8], [_yard(make)])  # loitering already a candidate, still open
    assert [u.status for u in running.updates if u.rule_id == "loitering"][-1] == "open"
    disabled = RulesConfig.model_validate({"rules": {"loitering": {"enabled": False}}})

    outcome = _process(make, running.state, sequence[8], [_yard(make)], config=disabled)

    assert [u.status for u in outcome.updates] == ["closed"]
    assert outcome.state.episodes == {}


def test_severity_from_the_configuration_is_recorded_on_the_candidate(
    make: SimpleNamespace,
) -> None:
    zone = make.zone("yard", "restricted")
    config = RulesConfig.model_validate(
        {"rules": {"intrusion.restricted": {"severity": "critical"}}}
    )
    sequence = make.twins(make.frames(3, [make.obj("cam01-t1")]), total_s=20)

    (candidate,) = [
        u
        for u in make.run(sequence, [zone], config=config).latest().values()
        if u.rule_id == "intrusion.restricted"
    ]

    assert candidate.severity == "critical"


def test_the_effective_params_are_recorded_for_traceability(make: SimpleNamespace) -> None:
    config = RulesConfig.model_validate(
        {"overrides": [{"rule": "loitering", "zone": "yard", "params": {"dwell_s": 5}}]}
    )
    sequence = make.twins(make.frames(5, [make.obj("cam01-t1")]), total_s=20)

    (candidate,) = [
        u
        for u in make.run(sequence, [_yard(make)], config=config).latest().values()
        if u.rule_id == "loitering"
    ]

    assert candidate.details["params"]["dwell_s"] == 5
    assert candidate.details["frames"] == 11
