"""The `@rule("<id>")` registry (CLAUDE.md "New event rule") — pure."""

from __future__ import annotations

import pytest
from events.domain.rules import base, get_rule, registered_rules
from events.domain.rules.base import CameraRule, RuleParams, ZoneRule, rule

BUILT_IN = {
    "intrusion.restricted",
    "intrusion.after_hours",
    "loitering",
    "crowding",
    "abandoned_object",
    "running",
}
ZONE_RULES = {"intrusion.restricted", "intrusion.after_hours", "loitering", "crowding"}
CAMERA_RULES = {"abandoned_object", "running"}


def test_every_built_in_rule_is_registered_under_its_id() -> None:
    rules = registered_rules()

    assert set(rules) == BUILT_IN
    for rule_id, instance in rules.items():
        assert instance.id == rule_id
        assert instance.event_type
        assert instance.default_severity in {"low", "medium", "high", "critical"}
        assert issubclass(instance.Params, RuleParams)


def test_rules_declare_whether_they_look_at_a_zone_or_the_whole_camera() -> None:
    rules = registered_rules()

    assert {rid for rid, r in rules.items() if r.scope == "zone"} == ZONE_RULES
    assert {rid for rid, r in rules.items() if r.scope == "camera"} == CAMERA_RULES
    assert all(isinstance(rules[rid], ZoneRule) for rid in ZONE_RULES)
    assert all(isinstance(rules[rid], CameraRule) for rid in CAMERA_RULES)


def test_get_rule_returns_the_registered_instance() -> None:
    assert get_rule("loitering") is registered_rules()["loitering"]


def test_an_unknown_rule_id_names_the_known_ones() -> None:
    with pytest.raises(ValueError, match="unknown rule id 'nope'.*crowding.*loitering"):
        get_rule("nope")


def test_registering_a_duplicate_id_is_refused() -> None:
    with pytest.raises(ValueError, match="already registered"):

        @rule("loitering")
        class Impostor(ZoneRule):  # pragma: no cover - never instantiated
            event_type = "loitering"
            default_severity = "low"
            Params = RuleParams

            def evaluate(self, zone, objects, params, ctx):
                return []


def test_a_new_rule_can_be_added_with_the_decorator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base, "_REGISTRY", dict(base._REGISTRY))  # isolate from other tests

    @rule("test.always")
    class Always(ZoneRule):
        event_type = "test"
        default_severity = "low"
        Params = RuleParams

        def evaluate(self, zone, objects, params, ctx):
            return []

    assert get_rule("test.always").id == "test.always"
    assert "test.always" in registered_rules()


def test_the_registry_copy_cannot_be_used_to_mutate_the_registry() -> None:
    snapshot = registered_rules()
    snapshot.clear()

    assert set(registered_rules()) == BUILT_IN
