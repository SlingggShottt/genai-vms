"""abandoned_object — a bag that stayed put for `static_s` (30 s) while nobody was
within `owner_radius` (0.08) for `unattended_s` (20 s) (design_architecture.md §7.3).
Camera-wide: needs no zones. Scenes are bags and owners moving at 2 fps."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from types import SimpleNamespace

import pytest
from events.domain.config import RulesConfig
from events.domain.state import CameraState
from pydantic import ValidationError

RULE = "abandoned_object"
BAG = (0.5, 0.5)
AWAY = (0.9, 0.5)  # far from BAG: distance 0.4, well beyond the 0.08 radius
NEAR = (0.52, 0.5)  # right next to the bag: distance 0.02


def _alarms(result) -> list:
    return [u for u in result.latest().values() if u.rule_id == RULE]


def _scene(
    make: SimpleNamespace,
    seconds: float,
    *,
    bag: tuple[float, float] | Callable[[float], tuple[float, float] | None] = BAG,
    bag_category: str = "backpack",
    bag_track: str = "cam01-t50",
    owner: Callable[[float], tuple[float, float] | None] | None = None,
    bag_visible: Callable[[float], bool] = lambda t: True,
) -> list:
    """Frame specs for a bag (still at `bag`, or following `bag(t)`) and an optional owner
    standing wherever `owner(t)` says (None = out of view), sampled every 0.5 s."""
    specs = []
    for i in range(round(seconds * 2) + 1):
        t = i / 2
        objects = []
        position = bag(t) if callable(bag) else bag
        if position is not None and bag_visible(t):
            objects.append(make.obj(bag_track, bag_category, zones=(), center=position))
        if owner is not None and (spot := owner(t)) is not None:
            objects.append(make.obj("cam01-t1", "person", zones=(), center=spot))
        specs.append((t, objects))
    return specs


def _leaves_at(seconds: float):
    return lambda t: NEAR if t < seconds else AWAY


def test_a_bag_left_behind_becomes_a_high_severity_candidate(make: SimpleNamespace) -> None:
    # The owner stands by the bag, walks away at 10 s, and never comes back.
    sequence = make.twins(_scene(make, 45, owner=_leaves_at(10)), total_s=70)

    result = make.run(sequence, zones=[])

    (c,) = _alarms(result)
    assert (c.rule_id, c.event_type, c.severity) == (RULE, "abandoned_object", "high")
    assert (c.zone_id, c.zone_name) == (None, None)
    assert c.track_ids == ["cam01-t50"]
    assert c.rule_score == 0.9
    assert c.details["peak_static_s"] >= 30
    assert c.details["peak_unattended_s"] >= 20


def test_the_candidate_starts_when_the_owner_walked_away_not_when_the_timers_ran_out(
    make: SimpleNamespace,
) -> None:
    sequence = make.twins(_scene(make, 45, owner=_leaves_at(10)), total_s=70)

    (c,) = _alarms(make.run(sequence, zones=[]))

    assert c.start_ts == make.T0 + timedelta(seconds=10)  # the moment worth showing in a clip
    assert c.end_ts == make.T0 + timedelta(seconds=45)


def test_nothing_is_reported_until_both_durations_have_elapsed(make: SimpleNamespace) -> None:
    sequence = make.twins(_scene(make, 45, owner=_leaves_at(10)), total_s=70)

    result = make.run(sequence, zones=[])

    # static since 0 s, unattended since 10 s -> the later of 30 s and 10 + 20 s = 30 s,
    # the first sample of the fourth segment.
    assert all(batch == [] for batch in result.per_twin[:3])
    assert len(result.per_twin[3]) == 1


def test_a_bag_nobody_ever_stood_next_to_is_unattended_from_the_start(
    make: SimpleNamespace,
) -> None:
    sequence = make.twins(_scene(make, 45), total_s=70)

    (c,) = _alarms(make.run(sequence, zones=[]))

    assert c.start_ts == make.T0


def test_the_owner_staying_beside_the_bag_never_triggers_it(make: SimpleNamespace) -> None:
    sequence = make.twins(_scene(make, 150, owner=lambda t: NEAR), total_s=170)

    assert _alarms(make.run(sequence, zones=[])) == []


def test_an_owner_who_comes_back_in_time_cancels_the_wait(make: SimpleNamespace) -> None:
    # Away from 10 s, back at 25 s: only 15 s unattended, short of the 20 s needed.
    owner = lambda t: AWAY if 10 <= t < 25 else NEAR  # noqa: E731
    sequence = make.twins(_scene(make, 120, owner=owner), total_s=140)

    assert _alarms(make.run(sequence, zones=[])) == []


def test_leaving_for_too_short_a_time_is_not_abandonment(make: SimpleNamespace) -> None:
    sequence = make.twins(_scene(make, 30, owner=_leaves_at(15)), total_s=60)  # 15 s unattended

    assert _alarms(make.run(sequence, zones=[])) == []


def test_a_bag_that_is_being_carried_never_counts_as_static(make: SimpleNamespace) -> None:
    drifting = lambda t: (0.2 + 0.02 * t, 0.5)  # noqa: E731 - 0.04/2 samples, beyond the 0.03 epsilon
    sequence = make.twins(_scene(make, 25, bag=drifting), total_s=60)

    assert _alarms(make.run(sequence, zones=[])) == []


def test_jitter_within_the_epsilon_still_counts_as_static(make: SimpleNamespace) -> None:
    wobble = lambda t: (0.5 + (0.01 if round(t * 2) % 2 else -0.01), 0.5)  # noqa: E731
    sequence = make.twins(_scene(make, 45, bag=wobble), total_s=70)

    assert len(_alarms(make.run(sequence, zones=[]))) == 1


def test_a_bag_that_creeps_slowly_away_is_not_static(make: SimpleNamespace) -> None:
    # 0.002 per sample is invisible sample to sample but adds up well past the epsilon from
    # where it first rested, so the clock keeps restarting.
    creeping = lambda t: (0.3 + 0.004 * t, 0.5)  # noqa: E731
    sequence = make.twins(_scene(make, 60, bag=creeping), total_s=90)

    assert _alarms(make.run(sequence, zones=[])) == []


def test_someone_just_inside_the_radius_attends_it_and_just_outside_does_not(
    make: SimpleNamespace,
) -> None:
    inside = make.twins(_scene(make, 45, owner=lambda t: (0.579, 0.5)), total_s=70)
    outside = make.twins(_scene(make, 45, owner=lambda t: (0.59, 0.5)), total_s=70)

    assert _alarms(make.run(inside, zones=[])) == []
    assert len(_alarms(make.run(outside, zones=[]))) == 1


def test_the_owner_radius_can_be_overridden_per_camera(make: SimpleNamespace) -> None:
    config = RulesConfig.model_validate(
        {"overrides": [{"rule": RULE, "camera": "cam01", "params": {"owner_radius": 0.6}}]}
    )
    sequence = make.twins(_scene(make, 45, owner=lambda t: AWAY), total_s=70)

    assert _alarms(make.run(sequence, zones=[], config=config)) == []  # AWAY is only 0.4 away


@pytest.mark.parametrize("category", ["backpack", "handbag", "suitcase"])
def test_every_bag_like_category_is_watched(make: SimpleNamespace, category: str) -> None:
    sequence = make.twins(_scene(make, 45, bag_category=category), total_s=70)

    assert len(_alarms(make.run(sequence, zones=[]))) == 1


def test_other_categories_are_not_abandoned_objects(make: SimpleNamespace) -> None:
    for category in ("car", "person", "bicycle"):
        sequence = make.twins(_scene(make, 60, bag_category=category), total_s=90)

        assert _alarms(make.run(sequence, zones=[])) == [], category


def test_two_unattended_bags_are_two_candidates(make: SimpleNamespace) -> None:
    first = _scene(make, 45, bag_track="cam01-t50", bag=(0.3, 0.5))
    second = _scene(make, 45, bag_track="cam01-t51", bag=(0.7, 0.5))
    merged = [(t, a + b) for (t, a), (_, b) in zip(first, second, strict=True)]

    candidates = _alarms(make.run(make.twins(merged, total_s=70), zones=[]))

    assert sorted(c.track_ids[0] for c in candidates) == ["cam01-t50", "cam01-t51"]


def test_a_missed_detection_or_two_does_not_restart_the_clock(make: SimpleNamespace) -> None:
    visible = lambda t: not (12 <= t < 14)  # noqa: E731 - gone for 2 s, within the 5 s debounce
    sequence = make.twins(_scene(make, 45, owner=_leaves_at(10), bag_visible=visible), total_s=70)

    (c,) = _alarms(make.run(sequence, zones=[]))

    assert c.start_ts == make.T0 + timedelta(seconds=10)


def test_losing_the_bag_for_longer_than_the_debounce_restarts_the_clock(
    make: SimpleNamespace,
) -> None:
    visible = lambda t: not (12 <= t < 19.5)  # noqa: E731 - 8 s gap, beyond the 5 s debounce
    sequence = make.twins(_scene(make, 70, owner=_leaves_at(10), bag_visible=visible), total_s=90)

    (c,) = _alarms(make.run(sequence, zones=[]))

    # Seen afresh at 19.5 s: still for 30 s from then -> the first hit is at 49.5 s...
    assert c.start_ts == make.T0 + timedelta(seconds=19.5)
    # ...and no update was produced before that.
    result = make.run(sequence, zones=[])
    first_batch = next(i for i, batch in enumerate(result.per_twin) if batch)
    assert first_batch == 4  # the 40-50 s segment


def test_a_gap_with_no_frames_at_all_still_restarts_the_clock(make: SimpleNamespace) -> None:
    # Not even the owner is in view for 8 s and the twin has no frames then (e.g. a recording gap),
    # so nothing gets a chance to prune the bag from memory: the rule must notice on its return.
    scene = _scene(make, 70, owner=_leaves_at(10))
    no_frames_between = [(t, objects) for t, objects in scene if not (12 <= t < 19.5)]

    (c,) = _alarms(make.run(make.twins(no_frames_between, total_s=90), zones=[]))

    assert c.start_ts == make.T0 + timedelta(seconds=19.5)  # seen afresh on its return


def test_frames_with_nothing_detected_let_the_rule_forget_a_bag_that_has_gone(
    make: SimpleNamespace,
) -> None:
    # A scene that empties out is a run of frames with no objects, not an absence of frames.
    # The rule is still consulted for them, which is how it drops what it was watching.
    emptied = _scene(make, 20, bag_visible=lambda t: t < 12)  # bag and owner both gone from 12 s

    result = make.run(make.twins(emptied, total_s=30), zones=[])

    assert _alarms(result) == []
    assert result.state.memory == {}


def test_the_candidate_closes_when_the_bag_is_picked_up(make: SimpleNamespace) -> None:
    gone_after_alarm = lambda t: t < 40  # noqa: E731
    sequence = make.twins(
        _scene(make, 60, owner=_leaves_at(10), bag_visible=gone_after_alarm), total_s=90
    )

    result = make.run(sequence, zones=[])

    (c,) = _alarms(result)
    assert c.status == "closed"
    assert c.end_ts == make.T0 + timedelta(seconds=39.5)
    assert result.state.memory == {}  # and the rule has forgotten the bag


def test_the_owner_returning_closes_it_and_a_second_abandonment_is_a_new_candidate(
    make: SimpleNamespace,
) -> None:
    # away 10-40 s (alarm), back 40-60 s, away again from 60 s -> a second alarm at 80 s
    owner = lambda t: NEAR if (t < 10 or 40 <= t < 60) else AWAY  # noqa: E731
    sequence = make.twins(_scene(make, 100, owner=owner), total_s=120)

    first, second = sorted(_alarms(make.run(sequence, zones=[])), key=lambda c: c.start_ts)

    assert (first.start_ts, first.status) == (make.T0 + timedelta(seconds=10), "closed")
    assert first.end_ts == make.T0 + timedelta(seconds=39.5)
    assert second.start_ts == make.T0 + timedelta(seconds=60)
    assert first.id != second.id


def test_the_candidate_keeps_one_id_while_it_extends_across_segments(make: SimpleNamespace) -> None:
    sequence = make.twins(_scene(make, 75, owner=_leaves_at(10)), total_s=100)

    result = make.run(sequence, zones=[])

    updates = [u for u in result.updates if u.rule_id == RULE]
    assert len({u.id for u in updates}) == 1
    assert len(updates) > 2
    assert [u.end_ts for u in updates] == sorted(u.end_ts for u in updates)


# --- the memory is part of the saved state ---------------------------------


def test_the_rules_memory_is_kept_in_the_state_while_it_watches_a_bag(
    make: SimpleNamespace,
) -> None:
    sequence = make.twins(_scene(make, 25, owner=_leaves_at(10)), total_s=30)[:2]

    result = make.run(sequence, zones=[])

    entry = result.state.memory[RULE]["cam01-t50"]
    assert entry["anchor"] == [0.5, 0.5]
    assert entry["static_since"] == make.T0.timestamp()
    assert entry["unattended_since"] == (make.T0 + timedelta(seconds=10)).timestamp()


def test_a_restart_in_the_middle_of_the_wait_changes_nothing(make: SimpleNamespace) -> None:
    sequence = make.twins(_scene(make, 75, owner=_leaves_at(10)), total_s=100)
    uninterrupted = make.run(sequence, zones=[])

    first_part = make.run(sequence[:2], zones=[])  # 20 s in: bag static, owner gone, no alarm yet
    reloaded = CameraState.model_validate_json(first_part.state.model_dump_json())
    second_part = make.run(sequence[2:], zones=[], state=reloaded)

    assert first_part.updates == []
    assert second_part.latest() == uninterrupted.latest()
    assert len(second_part.latest()) == 1


def test_without_the_saved_memory_a_restart_would_have_to_start_the_wait_over(
    make: SimpleNamespace,
) -> None:
    # Documents what checkpointing the memory is for. Lose the state at 20 s and the bag looks
    # newly seen then: 30 s of stillness again before it can alarm, and the candidate would
    # start at 20 s instead of the real 10 s.
    sequence = make.twins(_scene(make, 75, owner=_leaves_at(10)), total_s=100)

    cold_start = make.run(sequence[2:], zones=[])  # state lost at 20 s

    (c,) = _alarms(cold_start)
    assert c.start_ts == make.T0 + timedelta(seconds=20)
    first_alarm_segment = next(i for i, batch in enumerate(cold_start.per_twin) if batch)
    assert first_alarm_segment + 2 == 5  # the 50-60 s segment (offset by the two skipped twins)


def test_redelivering_a_twin_after_a_crash_gives_the_same_candidates(make: SimpleNamespace) -> None:
    from events.domain.engine import process_twin

    sequence = make.twins(_scene(make, 45, owner=_leaves_at(10)), total_s=70)
    before = make.run(sequence[:3], zones=[])

    kwargs = {"zones": [], "config": RulesConfig(), "site_tz": make.IST}
    one = process_twin(before.state, sequence[3], **kwargs)
    two = process_twin(before.state, sequence[3], **kwargs)

    assert one.updates == two.updates
    assert one.state == two.state
    assert len(one.updates) == 1


def test_a_camera_without_any_bag_keeps_no_memory(make: SimpleNamespace) -> None:
    sequence = make.twins(make.frames(20, [make.obj("cam01-t1", zones=())]), total_s=40)

    assert make.run(sequence, zones=[]).state.memory == {}


# --- configuration -----------------------------------------------------------


def test_it_cannot_be_overridden_per_zone_because_it_ignores_zones() -> None:
    with pytest.raises(ValidationError, match="whole camera view"):
        RulesConfig.model_validate(
            {"overrides": [{"rule": RULE, "zone": "lobby", "params": {"static_s": 5}}]}
        )


def test_the_durations_can_be_shortened_per_camera(make: SimpleNamespace) -> None:
    config = RulesConfig.model_validate(
        {
            "overrides": [
                {"rule": RULE, "camera": "cam01", "params": {"static_s": 6, "unattended_s": 4}}
            ]
        }
    )
    sequence = make.twins(_scene(make, 12, owner=_leaves_at(2)), total_s=40)

    (c,) = _alarms(make.run(sequence, zones=[], config=config))

    assert c.start_ts == make.T0 + timedelta(seconds=2)
    assert c.details["params"]["static_s"] == 6


@pytest.mark.parametrize(
    "bad", [{"static_s": 0}, {"unattended_s": -1}, {"owner_radius": 0}, {"static_epsilon": 0}]
)
def test_nonsensical_params_are_rejected_at_load(bad: dict) -> None:
    with pytest.raises(ValidationError):
        RulesConfig.model_validate({"rules": {RULE: {"params": bad}}})
