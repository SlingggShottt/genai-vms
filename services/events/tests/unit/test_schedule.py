"""Zone schedule evaluation for intrusion.after_hours (P3-D1) — pure."""

from __future__ import annotations

from datetime import datetime

import pytest
from events.domain.schedule import is_within_schedule, parse_hhmm
from vms_common.contracts.zones import ZoneSchedule

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri"]

# 2026-09-30 is a Wednesday, so 10-01 Thu, 10-02 Fri, 10-03 Sat, 10-04 Sun.
THU_NOON = datetime(2026, 10, 1, 12, 30)
SAT_NOON = datetime(2026, 10, 3, 12, 30)


def _schedule(start: str, end: str, days: list[str] | None = None) -> ZoneSchedule:
    kwargs = {"days": days} if days is not None else {}
    return ZoneSchedule(start_time=start, end_time=end, **kwargs)  # type: ignore[arg-type]


def test_parse_hhmm_reads_hours_and_minutes() -> None:
    assert parse_hhmm("08:30").hour == 8
    assert parse_hhmm("08:30").minute == 30
    assert parse_hhmm("00:00").hour == 0


@pytest.mark.parametrize("bad", ["9am", "25:00", "12:60", "12", "12:3x", "", "08:30:00"])
def test_parse_hhmm_rejects_anything_that_is_not_a_valid_clock_time(bad: str) -> None:
    with pytest.raises(ValueError, match="HH:MM"):
        parse_hhmm(bad)


def test_same_day_window_is_inside_during_the_day_and_outside_at_night() -> None:
    schedule = _schedule("09:00", "18:00", WEEKDAYS)

    assert is_within_schedule(schedule, THU_NOON) is True
    assert is_within_schedule(schedule, datetime(2026, 10, 1, 20, 0)) is False
    assert is_within_schedule(schedule, datetime(2026, 10, 1, 3, 0)) is False


def test_window_start_is_inclusive_and_end_is_exclusive() -> None:
    schedule = _schedule("09:00", "18:00", WEEKDAYS)

    assert is_within_schedule(schedule, datetime(2026, 10, 1, 9, 0)) is True
    assert is_within_schedule(schedule, datetime(2026, 10, 1, 8, 59, 59)) is False
    assert is_within_schedule(schedule, datetime(2026, 10, 1, 17, 59, 59)) is True
    assert is_within_schedule(schedule, datetime(2026, 10, 1, 18, 0)) is False


def test_a_day_not_in_the_schedule_is_outside_even_at_working_hours() -> None:
    schedule = _schedule("09:00", "18:00", WEEKDAYS)

    assert is_within_schedule(schedule, SAT_NOON) is False


def test_days_default_to_every_day_of_the_week() -> None:
    schedule = _schedule("09:00", "18:00")

    assert is_within_schedule(schedule, SAT_NOON) is True


def test_overnight_window_covers_late_evening_and_the_early_morning_after() -> None:
    schedule = _schedule("22:00", "06:00", WEEKDAYS)

    assert is_within_schedule(schedule, datetime(2026, 10, 1, 23, 0)) is True  # Thu night
    assert is_within_schedule(schedule, datetime(2026, 10, 2, 2, 0)) is True  # Fri, opened Thu
    assert is_within_schedule(schedule, datetime(2026, 10, 1, 12, 0)) is False  # Thu daytime


def test_overnight_window_belongs_to_the_day_it_opens_on() -> None:
    schedule = _schedule("22:00", "06:00", WEEKDAYS)

    # Fri 22:00 -> Sat 06:00 is a Friday window, so Sat 02:00 is inside it...
    assert is_within_schedule(schedule, datetime(2026, 10, 3, 2, 0)) is True
    # ...but Sat 22:00 -> Sun 06:00 would be a Saturday window, which isn't scheduled.
    assert is_within_schedule(schedule, datetime(2026, 10, 3, 23, 0)) is False
    assert is_within_schedule(schedule, datetime(2026, 10, 4, 2, 0)) is False


def test_equal_start_and_end_means_the_whole_day_on_the_listed_days() -> None:
    schedule = _schedule("00:00", "00:00", WEEKDAYS)

    assert is_within_schedule(schedule, datetime(2026, 10, 1, 3, 0)) is True
    assert is_within_schedule(schedule, datetime(2026, 10, 1, 23, 59)) is True
    assert is_within_schedule(schedule, SAT_NOON) is False


def test_a_malformed_time_raises_instead_of_guessing() -> None:
    with pytest.raises(ValueError, match="HH:MM"):
        is_within_schedule(_schedule("nine", "18:00"), THU_NOON)
