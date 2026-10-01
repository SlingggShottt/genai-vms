"""Load and validate `config/rules.yaml` (design_architecture.md §7.3)."""

from __future__ import annotations

from pathlib import Path

import yaml

from events.domain.config import RulesConfig


def load_rules_config(path: str | Path) -> RulesConfig:
    """Parse the YAML file into a validated `RulesConfig`.

    Raises `FileNotFoundError` if the file is missing, `yaml.YAMLError` for
    malformed YAML and `pydantic.ValidationError` for unknown rules, unknown or
    out-of-range params and badly scoped overrides — so the service refuses to
    start on a bad file instead of running with silently different thresholds.
    An empty file is valid: every rule runs with its built-in defaults.
    """
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return RulesConfig.model_validate(raw)
