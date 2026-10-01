"""running — a person faster than `speed` (0.35/s) for at least `min_samples`
(3) samples (design_architecture.md §7.3). Camera-wide: needs no zones."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from events.domain.config import RulesConfig
from pydantic import ValidationError

RULE = "running"


def _runs(result) -> list:
    return [u for u in result.latest().values() if u.rule_id == RULE]


def _runner(make: SimpleNamespace, track: str = "cam01-t1", speed: float = 0.5, **kw):
    return make.obj(track, zones=(), speed=speed, **kw)


def test_a_person_running_for_the_minimum_samples_raises_a_low_severity_event(
    make: SimpleNamespace,
) -> None:
    # 1 s at 2 fps = 3 samples (0, 0.5, 1.0).
    sequence = make.twins(make.frames(1, [_runner(make, speed=0.5, conf=0.8)]), total_s=20)

    (c,) = _runs(make.run(sequence, zones=[]))

    assert (c.rule_id, c.event_type, c.severity) == (RULE, "running", "low")
    assert (c.zone_id, c.zone_name) == (None, None)  # camera-wide: no zone
    assert c.track_ids == ["cam01-t1"]
    assert (c.start_ts, c.end_ts) == (make.T0, make.T0 + timedelta(seconds=1))
    assert c.details["peak_speed"] == 0.5
    assert c.details["frames"] == 3
    assert 0.5 < c.rule_score <= 1.0


def test_it_works_on_a_camera_with_no_zones_and_outside_any_zone(make: SimpleNamespace) -> None:
    sequence = make.twins(make.frames(2, [_runner(make)]), total_s=20)

    assert len(_runs(make.run(sequence, zones=[]))) == 1
    # a zone that exists but the runner isn't in changes nothing
    assert len(_runs(make.run(sequence, zones=[make.zone("yard", "restricted")]))) == 1


def test_walking_pace_is_not_running(make: SimpleNamespace) -> None:
    sequence = make.twins(make.frames(10, [_runner(make, speed=0.1)]), total_s=30)

    assert _runs(make.run(sequence, zones=[])) == []


def test_the_speed_threshold_is_strict(make: SimpleNamespace) -> None:
    exactly = make.twins(make.frames(10, [_runner(make, speed=0.35)]), total_s=30)
    just_over = make.twins(make.frames(10, [_runner(make, speed=0.351)]), total_s=30)

    assert _runs(make.run(exactly, zones=[])) == []
    assert len(_runs(make.run(just_over, zones=[]))) == 1


def test_two_fast_samples_are_not_enough(make: SimpleNamespace) -> None:
    sequence = make.twins(make.frames(0.5, [_runner(make)]), total_s=20)  # 2 samples

    assert _runs(make.run(sequence, zones=[])) == []


def test_samples_without_motion_data_are_ignored(make: SimpleNamespace) -> None:
    unmeasured = make.obj("cam01-t1", zones=(), speed=None)  # e.g. the first frame of a track
    sequence = make.twins(make.frames(10, [unmeasured]), total_s=30)

    assert _runs(make.run(sequence, zones=[])) == []


def test_vehicles_are_not_runners(make: SimpleNamespace) -> None:
    sequence = make.twins(make.frames(10, [_runner(make, category="car", speed=2.0)]), total_s=30)

    assert _runs(make.run(sequence, zones=[])) == []


def test_two_runners_are_two_candidates(make: SimpleNamespace) -> None:
    both = [_runner(make, "cam01-t1"), _runner(make, "cam01-t2", speed=0.9)]
    sequence = make.twins(make.frames(2, both), total_s=20)

    candidates = _runs(make.run(sequence, zones=[]))

    assert sorted(c.track_ids[0] for c in candidates) == ["cam01-t1", "cam01-t2"]


def test_a_brief_slowdown_within_the_debounce_keeps_one_candidate(make: SimpleNamespace) -> None:
    runner = [_runner(make)]
    # fast 0-2 s, slow for 1.5 s (< the 2 s debounce), fast again 3.5-5 s
    specs = make.frames(2, runner) + make.frames(1.5, runner, start=3.5)

    (c,) = _runs(make.run(make.twins(specs, total_s=30), zones=[]))

    assert (c.start_ts, c.end_ts) == (make.T0, make.T0 + timedelta(seconds=5))


def test_a_pause_longer_than_the_debounce_splits_the_run(make: SimpleNamespace) -> None:
    runner = [_runner(make)]
    # two bursts of exactly 3 samples, 3 s apart (> the 2 s debounce): two candidates
    specs = make.frames(1, runner) + make.frames(1, runner, start=4.0)

    candidates = sorted(
        _runs(make.run(make.twins(specs, total_s=30), zones=[])), key=lambda c: c.start_ts
    )

    assert len(candidates) == 2
    assert candidates[1].start_ts == make.T0 + timedelta(seconds=4)


def test_a_long_run_extends_one_candidate_across_segments_then_closes(
    make: SimpleNamespace,
) -> None:
    sequence = make.twins(make.frames(25, [_runner(make)]), total_s=45)

    result = make.run(sequence, zones=[])

    updates = [u for u in result.updates if u.rule_id == RULE]
    assert len({u.id for u in updates}) == 1
    assert updates[-1].status == "closed"
    assert updates[-1].end_ts == make.T0 + timedelta(seconds=25)
    assert len(updates[-1].segment_ids) == 3


def test_the_speed_limit_can_be_overridden_for_one_camera(make: SimpleNamespace) -> None:
    config = RulesConfig.model_validate(
        {"overrides": [{"rule": RULE, "camera": "cam02", "params": {"speed": 0.05}}]}
    )
    jogger = [_runner(make, speed=0.1)]
    cam1 = make.twins(make.frames(3, jogger), total_s=20)
    cam2 = make.twins(
        make.frames(3, [_runner(make, "cam02-t1", speed=0.1)]), camera_id="cam02", total_s=20
    )

    assert _runs(make.run(cam1, zones=[], config=config)) == []
    assert len(_runs(make.run(cam2, zones=[], config=config, camera_id="cam02"))) == 1


def test_it_can_be_switched_off(make: SimpleNamespace) -> None:
    config = RulesConfig.model_validate({"rules": {RULE: {"enabled": False}}})
    sequence = make.twins(make.frames(5, [_runner(make)]), total_s=20)

    assert _runs(make.run(sequence, zones=[], config=config)) == []


def test_it_cannot_be_overridden_per_zone_because_it_ignores_zones() -> None:
    with pytest.raises(ValidationError, match="whole camera view"):
        RulesConfig.model_validate(
            {"overrides": [{"rule": RULE, "zone": "lobby", "params": {"speed": 0.1}}]}
        )


def test_the_minimum_samples_is_configurable(make: SimpleNamespace) -> None:
    config = RulesConfig.model_validate({"rules": {RULE: {"params": {"min_samples": 1}}}})
    sequence = make.twins([(0.0, [_runner(make)])], total_s=20)

    assert len(_runs(make.run(sequence, zones=[], config=config))) == 1
