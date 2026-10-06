from datetime import date

from reasoning.reports.facts import DailyFacts, template_narrative, unsupported_numbers


def _facts(**kw):
    base = {
        "date_from": date(2026, 10, 4),
        "date_to": date(2026, 10, 4),
        "timezone": "Asia/Kolkata",
        "events_total": 6,
        "by_type": {"intrusion": 6},
        "by_camera": {"cam01": 6},
        "by_severity": {"high": 6},
        "by_hour": {"12": 6},
        "incidents_total": 3,
    }
    return DailyFacts(**{**base, **kw})


def test_a_narrative_may_only_use_numbers_the_figures_contain():
    f = _facts()
    assert unsupported_numbers("6 events and 3 incident reports on 4 October 2026.", f) == []
    assert unsupported_numbers("There were 42 events.", f) == ["42"]


def test_clock_times_pass_only_as_whole_hours_in_the_figures():
    f = _facts()
    assert unsupported_numbers("The busiest hour began at 12:00.", f) == []
    assert unsupported_numbers("It peaked at 12:37.", f) == ["12:37"]
    assert unsupported_numbers("It peaked at 18:00.", f) == ["18:00"]


def test_template_uses_only_the_figures_and_names_a_single_day_or_a_range():
    f = _facts()
    text = template_narrative(f)
    assert text.startswith("On Sunday 04 October 2026")
    assert unsupported_numbers(text, f) == []
    empty = template_narrative(_facts(events_total=0, incidents_total=0, by_type={}, by_hour={}))
    assert "Nothing was recorded" in empty
    span = template_narrative(_facts(date_to=date(2026, 10, 6)))
    assert span.startswith("From 04 October 2026 to 06 October 2026")
