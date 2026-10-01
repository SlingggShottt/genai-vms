"""Rule configuration: defaults, per-camera/zone overrides, validation (P3-D1 AC:
"thresholds from config/rules.yaml overridable per camera/zone") — pure."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from events.domain.config import RulesConfig
from events.domain.rules import registered_rules
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[4]


def _config(**sections: Any) -> RulesConfig:
    return RulesConfig.model_validate(sections)


# --- built-in defaults ---------------------------------------------------


def test_an_empty_config_enables_every_rule_with_the_design_defaults() -> None:
    config = RulesConfig()

    restricted = config.resolve("intrusion.restricted", "cam01", "yard")
    after_hours = config.resolve("intrusion.after_hours", "cam01", "yard")
    loitering = config.resolve("loitering", "cam01", "yard")
    crowding = config.resolve("crowding", "cam01", "yard")

    assert all(r.enabled for r in (restricted, after_hours, loitering, crowding))
    assert (restricted.severity, after_hours.severity) == ("high", "high")
    assert (loitering.severity, crowding.severity) == ("medium", "medium")
    assert restricted.params.min_frames == 2  # design §7.3
    assert loitering.params.dwell_s == 60  # T = 60 s
    assert (crowding.params.max_persons, crowding.params.duration_s) == (8, 20)  # N = 8, T = 20 s


def test_the_shipped_rules_yaml_loads_and_matches_the_built_in_defaults() -> None:
    raw = yaml.safe_load((REPO_ROOT / "config" / "rules.yaml").read_text())

    shipped = RulesConfig.model_validate(raw)
    built_in = RulesConfig()

    assert set(shipped.rules) == set(registered_rules())
    for rule_id in registered_rules():
        a = shipped.resolve(rule_id, "cam01", "yard")
        b = built_in.resolve(rule_id, "cam01", "yard")
        assert a.params == b.params, rule_id
        assert (a.enabled, a.severity, a.verify) == (b.enabled, b.severity, b.verify), rule_id
    assert shipped.overrides == []


def test_every_rule_exposes_a_json_schema_for_its_params() -> None:
    for rule in registered_rules().values():
        schema = rule.Params.model_json_schema()
        assert schema["additionalProperties"] is False
        assert "debounce_s" in schema["properties"]


# --- the rules: block ----------------------------------------------------


def test_a_rules_entry_replaces_defaults_and_unlisted_params_keep_theirs() -> None:
    config = _config(rules={"loitering": {"params": {"dwell_s": 90}}})

    loitering = config.resolve("loitering", "cam01", "yard")

    assert loitering.params.dwell_s == 90
    assert loitering.params.debounce_s == 5.0  # untouched default
    assert loitering.params.categories == ["person"]


def test_a_rule_left_out_of_the_file_stays_enabled() -> None:
    config = _config(rules={"loitering": {"enabled": False}})

    assert config.resolve("loitering", "cam01", "yard").enabled is False
    assert config.resolve("crowding", "cam01", "yard").enabled is True


def test_severity_and_verify_can_be_set_per_rule() -> None:
    config = _config(rules={"crowding": {"severity": "low", "verify": False}})

    crowding = config.resolve("crowding", "cam01", "yard")

    assert crowding.severity == "low"
    assert crowding.verify is False


# --- overrides -----------------------------------------------------------


def test_a_camera_override_applies_only_to_that_camera() -> None:
    config = _config(
        overrides=[{"rule": "loitering", "camera": "cam02", "params": {"dwell_s": 30}}]
    )

    assert config.resolve("loitering", "cam02", "yard").params.dwell_s == 30
    assert config.resolve("loitering", "cam01", "yard").params.dwell_s == 60


def test_a_zone_override_applies_to_that_zone_name_on_any_camera() -> None:
    config = _config(overrides=[{"rule": "loitering", "zone": "lobby", "params": {"dwell_s": 15}}])

    assert config.resolve("loitering", "cam01", "lobby").params.dwell_s == 15
    assert config.resolve("loitering", "cam07", "lobby").params.dwell_s == 15
    assert config.resolve("loitering", "cam01", "yard").params.dwell_s == 60


def test_more_specific_overrides_win_camera_then_zone_then_camera_and_zone() -> None:
    config = _config(
        rules={"loitering": {"params": {"dwell_s": 100}}},
        overrides=[
            # Deliberately listed most-specific first: order must not matter between ranks.
            {"rule": "loitering", "camera": "cam01", "zone": "lobby", "params": {"dwell_s": 4}},
            {"rule": "loitering", "zone": "lobby", "params": {"dwell_s": 3}},
            {"rule": "loitering", "camera": "cam01", "params": {"dwell_s": 2}},
        ],
    )

    assert config.resolve("loitering", "cam09", "yard").params.dwell_s == 100  # nothing matches
    assert config.resolve("loitering", "cam01", "yard").params.dwell_s == 2  # camera
    assert config.resolve("loitering", "cam09", "lobby").params.dwell_s == 3  # zone
    assert config.resolve("loitering", "cam01", "lobby").params.dwell_s == 4  # camera + zone


def test_zone_beats_camera_when_both_match_without_the_pair_override() -> None:
    config = _config(
        overrides=[
            {"rule": "loitering", "camera": "cam01", "params": {"dwell_s": 2}},
            {"rule": "loitering", "zone": "lobby", "params": {"dwell_s": 3}},
        ]
    )

    assert config.resolve("loitering", "cam01", "lobby").params.dwell_s == 3


def test_later_overrides_win_a_tie_of_equal_specificity() -> None:
    config = _config(
        overrides=[
            {"rule": "loitering", "camera": "cam01", "params": {"dwell_s": 20}},
            {"rule": "loitering", "camera": "cam01", "params": {"dwell_s": 25}},
        ]
    )

    assert config.resolve("loitering", "cam01", "yard").params.dwell_s == 25


def test_overrides_merge_params_instead_of_replacing_them() -> None:
    config = _config(
        rules={"crowding": {"params": {"max_persons": 12, "duration_s": 30}}},
        overrides=[{"rule": "crowding", "zone": "lobby", "params": {"max_persons": 25}}],
    )

    lobby = config.resolve("crowding", "cam01", "lobby")

    assert (lobby.params.max_persons, lobby.params.duration_s) == (25, 30)


def test_an_override_can_disable_a_rule_and_change_severity_and_verify() -> None:
    config = _config(
        overrides=[
            {"rule": "intrusion.after_hours", "zone": "car-park", "enabled": False},
            {"rule": "crowding", "camera": "cam02", "severity": "high", "verify": False},
        ]
    )

    assert config.resolve("intrusion.after_hours", "cam01", "car-park").enabled is False
    assert config.resolve("intrusion.after_hours", "cam01", "yard").enabled is True
    crowding = config.resolve("crowding", "cam02", "yard")
    assert (crowding.severity, crowding.verify) == ("high", False)


def test_overrides_for_other_rules_are_ignored() -> None:
    config = _config(
        overrides=[{"rule": "crowding", "camera": "cam01", "params": {"max_persons": 50}}]
    )

    assert config.resolve("loitering", "cam01", "yard").params.dwell_s == 60


def test_resolving_twice_gives_the_same_answer() -> None:
    config = _config(overrides=[{"rule": "loitering", "camera": "cam01", "params": {"dwell_s": 7}}])

    assert config.resolve("loitering", "cam01", "yard") is config.resolve(
        "loitering", "cam01", "yard"
    )


# --- validation: mistakes fail at load time -------------------------------


@pytest.mark.parametrize(
    ("sections", "message"),
    [
        ({"rules": {"loiterng": {}}}, "unknown rule id 'loiterng'"),
        ({"overrides": [{"rule": "nope", "camera": "cam01"}]}, "unknown rule id 'nope'"),
        ({"rules": {"loitering": {"params": {"dwell": 30}}}}, "dwell"),  # typo of dwell_s
        ({"rules": {"loitering": {"params": {"dwell_s": 0}}}}, "dwell_s"),
        ({"rules": {"crowding": {"params": {"max_persons": 0}}}}, "max_persons"),
        ({"rules": {"loitering": {"params": {"zone_types": ["lobby"]}}}}, "zone_types"),
        ({"rules": {"loitering": {"severity": "urgent"}}}, "severity"),
        ({"rules": {"loitering": {"enabledd": True}}}, "enabledd"),
        ({"overrides": [{"rule": "loitering", "params": {"dwell_s": 5}}]}, "camera and/or a zone"),
        (
            {"overrides": [{"rule": "loitering", "camera": "cam01", "params": {"dwell_s": -1}}]},
            "dwell_s",
        ),
        ({"version": 2}, "version"),
        ({"rulez": {}}, "rulez"),
    ],
)
def test_invalid_configuration_is_rejected_with_a_message_naming_the_problem(
    sections: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        RulesConfig.model_validate(sections)
