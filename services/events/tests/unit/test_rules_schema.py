"""JSON Schema of the rules file, generated from the rule registry (P3-D2 AC:
"each [rule] with a JSON-schema for its params") — pure."""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path
from typing import get_args

import pytest
import yaml
from events.domain.rules import Severity, registered_rules
from events.domain.schema import SEVERITIES, rule_param_schemas, rules_file_schema
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[4]
SCHEMA_FILE = REPO_ROOT / "config" / "rules.schema.json"
RULES_FILE = REPO_ROOT / "config" / "rules.yaml"


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    return Draft202012Validator(rules_file_schema())


def _errors(validator: Draft202012Validator, document: dict) -> list[str]:
    return [e.message for e in validator.iter_errors(document)]


def test_every_rule_has_a_params_schema_that_matches_its_model() -> None:
    schemas = rule_param_schemas()

    assert set(schemas) == set(registered_rules())
    for rule_id, rule in registered_rules().items():
        schema = schemas[rule_id]
        assert set(schema["properties"]) == set(rule.Params.model_fields), rule_id
        assert schema["additionalProperties"] is False, rule_id


def test_the_whole_file_schema_is_itself_a_valid_json_schema() -> None:
    Draft202012Validator.check_schema(rules_file_schema())


def test_the_schema_hoists_nothing_it_cannot_resolve() -> None:
    # Per-rule schemas are embedded as-is, so none may point at a `$defs` of its own.
    assert "$defs" not in str(rules_file_schema())


def test_severities_in_the_schema_match_the_python_type() -> None:
    assert set(SEVERITIES) == set(get_args(Severity))


def test_the_shipped_rules_yaml_conforms_to_the_schema(validator: Draft202012Validator) -> None:
    document = yaml.safe_load(RULES_FILE.read_text())

    assert _errors(validator, document) == []


def test_an_empty_or_minimal_file_conforms(validator: Draft202012Validator) -> None:
    assert _errors(validator, {}) == []
    assert (
        _errors(validator, {"version": 1, "rules": {"loitering": {"params": {"dwell_s": 90}}}})
        == []
    )


def test_a_valid_override_conforms(validator: Draft202012Validator) -> None:
    document = {
        "overrides": [
            {"rule": "loitering", "camera": "cam02", "params": {"dwell_s": 30}},
            {"rule": "crowding", "zone": "lobby", "params": {"max_persons": 20}},
            {"rule": "running", "camera": "cam01", "params": {"speed": 0.2}},
        ]
    }

    assert _errors(validator, document) == []


@pytest.mark.parametrize(
    ("document", "why"),
    [
        ({"rules": {"loitering": {"params": {"dwell": 30}}}}, "typo'd param name"),
        ({"rules": {"loitering": {"params": {"dwell_s": 0}}}}, "value out of range"),
        ({"rules": {"loitering": {"params": {"zone_types": ["lobby"]}}}}, "unknown zone type"),
        ({"rules": {"loiterng": {}}}, "unknown rule"),
        ({"rules": {"loitering": {"severity": "urgent"}}}, "bad severity"),
        ({"rules": {"loitering": {"enabledd": True}}}, "typo'd setting"),
        ({"version": 2}, "wrong version"),
        ({"rulez": {}}, "unknown top-level key"),
        (
            {"overrides": [{"rule": "loitering", "params": {"dwell_s": 5}}]},
            "override with no scope",
        ),
        (
            {"overrides": [{"rule": "running", "zone": "lobby", "params": {"speed": 0.2}}]},
            "per-zone override of a camera-wide rule",
        ),
        (
            {"overrides": [{"rule": "running", "camera": "cam01", "params": {"dwell_s": 5}}]},
            "another rule's param",
        ),
        ({"overrides": [{"camera": "cam01", "params": {}}]}, "override naming no rule"),
    ],
)
def test_the_schema_rejects_the_same_mistakes_the_loader_does(
    validator: Draft202012Validator, document: dict, why: str
) -> None:
    assert _errors(validator, document), why


def test_the_committed_schema_file_is_up_to_date() -> None:
    expected = rules_file_schema()

    import json

    assert json.loads(SCHEMA_FILE.read_text()) == expected, (
        "config/rules.schema.json is stale — run "
        "`uv run --package vms-events python -m events.schema_export --write`"
    )


def test_the_export_command_agrees_with_the_committed_file() -> None:
    result = subprocess.run(  # noqa: S603 - fixed command, no untrusted input
        [sys.executable, "-m", "events.schema_export", "--check", "--path", str(SCHEMA_FILE)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_the_export_command_reports_a_stale_file(tmp_path: Path) -> None:
    stale = tmp_path / "rules.schema.json"
    stale.write_text("{}\n")

    result = subprocess.run(  # noqa: S603 - fixed command, no untrusted input
        [sys.executable, "-m", "events.schema_export", "--check", "--path", str(stale)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "stale" in result.stdout


def test_every_rule_block_in_the_shipped_file_is_known_to_the_schema() -> None:
    schema = copy.deepcopy(rules_file_schema())
    listed = set(yaml.safe_load(RULES_FILE.read_text())["rules"])

    assert listed == set(schema["properties"]["rules"]["properties"])
