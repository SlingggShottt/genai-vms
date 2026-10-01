"""Zone schedule evaluation for `intrusion.after_hours` — pure.

A zone's `schedule` (`core.zones.schedule`, `ZoneSchedule`) is the window in
which the zone is **normally in use**; a person there *outside* it is an
after-hours intrusion (design_architecture.md §7.3: "any person in zone
outside its schedule"). Times are site-local `HH:MM`, so callers convert the
frame's UTC timestamp to the site's timezone first.
"""

from __future__ import annotations

from datetime import datetime, time

from vms_common.contracts.zones import ZoneSchedule

_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def parse_hhmm(value: str) -> time:
    """`"08:30"` -> `time(8, 30)`. Raises `ValueError` for anything else."""
    try:
        hours, minutes = value.split(":")
        return time(int(hours), int(minutes))
    except ValueError as exc:
        raise ValueError(f"expected HH:MM between 00:00 and 23:59, got {value!r}") from exc


def is_within_schedule(schedule: ZoneSchedule, local_dt: datetime) -> bool:
    """Whether `local_dt` (site-local wall-clock) is inside the schedule's window.

    - `start < end`: a same-day window; `days` are the days it is active.
    - `start > end`: an overnight window (e.g. 22:00-06:00). It belongs to the
      day it *opens* on, so at 02:00 on Tuesday the relevant day is Monday.
    - `start == end`: treated as the whole day on the listed days.

    Raises `ValueError` if a time is not valid `HH:MM`.
    """
    start = parse_hhmm(schedule.start_time)
    end = parse_hhmm(schedule.end_time)
    now = local_dt.time()
    weekday = local_dt.weekday()
    days = set(schedule.days)

    if start == end:
        return _WEEKDAYS[weekday] in days
    if start < end:
        return _WEEKDAYS[weekday] in days and start <= now < end
    if now >= start:  # overnight window that opened today
        return _WEEKDAYS[weekday] in days
    if now < end:  # overnight window that opened yesterday
        return _WEEKDAYS[(weekday - 1) % 7] in days
    return False
