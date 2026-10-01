"""intrusion.after_hours — a person in a zone outside that zone's schedule
(design_architecture.md §7.3). Schedules are site-local (IST in these tests)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from events.domain.config import RulesConfig
from vms_common.contracts.zones import ZoneSchedule

RULE = "intrusion.after_hours"
OFFICE_HOURS = ZoneSchedule(
    start_time="09:00", end_time="18:00", days=["mon", "tue", "wed", "thu", "fri"]
)

# IST = UTC+5:30.  2026-10-01 is a Thursday.
THU_20_00_IST = datetime(2026, 10, 1, 14, 30, tzinfo=UTC)
THU_12_30_IST = datetime(2026, 10, 1, 7, 0, tzinfo=UTC)
SAT_12_30_IST = datetime(2026, 10, 3, 7, 0, tzinfo=UTC)
THU_17_59_50_IST = datetime(2026, 10, 1, 12, 29, 50, tzinfo=UTC)


def _hits(result) -> list:
    return [u for u in result.latest().values() if u.rule_id == RULE]


def _person_in_office(
    make: SimpleNamespace, start: datetime, seconds: float = 3, category: str = "person"
) -> list:
    """Twins of one object standing in the zone named "office" for `seconds`."""
    return make.twins(
        make.frames(seconds, [make.obj("cam01-t5", category, zones=("office",))]), start=start
    )


def test_a_person_in_a_scheduled_zone_outside_its_hours_raises_a_high_severity_intrusion(
    make: SimpleNamespace,
) -> None:
    zone = make.zone("office", "generic", schedule=OFFICE_HOURS)

    candidates = _hits(make.run(_person_in_office(make, THU_20_00_IST), [zone]))

    assert len(candidates) == 1
    c = candidates[0]
    assert (c.rule_id, c.event_type, c.severity) == (RULE, "intrusion", "high")
    assert (c.zone_id, c.zone_name) == ("zone-office", "office")
    assert c.track_ids == ["cam01-t5"]
    assert c.start_ts == THU_20_00_IST


def test_the_same_person_during_the_zones_hours_is_fine(make: SimpleNamespace) -> None:
    zone = make.zone("office", "generic", schedule=OFFICE_HOURS)

    assert _hits(make.run(_person_in_office(make, THU_12_30_IST), [zone])) == []


def test_a_day_the_zone_is_not_scheduled_counts_as_outside_hours(make: SimpleNamespace) -> None:
    zone = make.zone("office", "generic", schedule=OFFICE_HOURS)

    assert len(_hits(make.run(_person_in_office(make, SAT_12_30_IST), [zone]))) == 1


def test_a_zone_without_a_schedule_never_triggers(make: SimpleNamespace) -> None:
    zone = make.zone("office", "generic", schedule=None)

    assert _hits(make.run(_person_in_office(make, THU_20_00_IST), [zone])) == []


def test_it_applies_to_any_zone_type_that_has_a_schedule(make: SimpleNamespace) -> None:
    for zone_type in ("generic", "restricted", "entrance", "exit"):
        zone = make.zone("office", zone_type, schedule=OFFICE_HOURS)

        assert len(_hits(make.run(_person_in_office(make, THU_20_00_IST), [zone]))) == 1, zone_type


def test_vehicles_do_not_trigger_it(make: SimpleNamespace) -> None:
    zone = make.zone("office", "generic", schedule=OFFICE_HOURS)

    assert _hits(make.run(_person_in_office(make, THU_20_00_IST, category="car"), [zone])) == []


def test_a_single_frame_is_not_enough(make: SimpleNamespace) -> None:
    zone = make.zone("office", "generic", schedule=OFFICE_HOURS)
    twins = make.twins([(0.0, [make.obj("cam01-t5", zones=("office",))])], start=THU_20_00_IST)

    assert _hits(make.run(twins, [zone])) == []


def test_an_overnight_schedule_is_evaluated_across_midnight(make: SimpleNamespace) -> None:
    night_shift = ZoneSchedule(start_time="22:00", end_time="06:00")  # every day
    zone = make.zone("office", "generic", schedule=night_shift)
    midday = _person_in_office(make, THU_12_30_IST)  # 12:30 IST: outside the 22:00-06:00 shift
    late = _person_in_office(make, datetime(2026, 10, 1, 17, 30, tzinfo=UTC))  # 23:00 IST: inside

    assert len(_hits(make.run(midday, [zone]))) == 1
    assert _hits(make.run(late, [zone])) == []


def test_staying_past_closing_time_starts_the_candidate_exactly_when_hours_end(
    make: SimpleNamespace,
) -> None:
    zone = make.zone("office", "generic", schedule=OFFICE_HOURS)
    # 17:59:50 -> 18:00:10 IST. The zone closes at 18:00:00 IST = 12:30:00 UTC.
    twins = _person_in_office(make, THU_17_59_50_IST, seconds=20)

    candidates = _hits(make.run(twins, [zone]))

    assert len(candidates) == 1
    assert candidates[0].start_ts == datetime(2026, 10, 1, 12, 30, 0, tzinfo=UTC)


def test_a_malformed_schedule_is_ignored_rather_than_treated_as_always_after_hours(
    make: SimpleNamespace,
) -> None:
    broken = ZoneSchedule(start_time="nine", end_time="18:00")
    zone = make.zone("office", "generic", schedule=broken)

    assert _hits(make.run(_person_in_office(make, THU_20_00_IST), [zone])) == []


def test_it_can_be_switched_off_for_one_zone(make: SimpleNamespace) -> None:
    zone = make.zone("office", "generic", schedule=OFFICE_HOURS)
    config = RulesConfig.model_validate(
        {"overrides": [{"rule": RULE, "zone": "office", "enabled": False}]}
    )

    assert _hits(make.run(_person_in_office(make, THU_20_00_IST), [zone], config=config)) == []


def test_a_scheduled_restricted_zone_raises_both_intrusion_rules(make: SimpleNamespace) -> None:
    zone = make.zone("office", "restricted", schedule=OFFICE_HOURS)

    result = make.run(_person_in_office(make, THU_20_00_IST), [zone])

    assert {u.rule_id for u in result.latest().values()} >= {
        "intrusion.restricted",
        "intrusion.after_hours",
    }
