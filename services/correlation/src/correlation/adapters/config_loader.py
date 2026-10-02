"""Load and validate `config/correlation.yaml` (a bad file stops the service at startup)."""

from __future__ import annotations

from pathlib import Path

import yaml

from correlation.domain.config import CorrelationConfig


def load_correlation_config(path: str | Path) -> CorrelationConfig:
    """Raises `OSError` (unreadable), `ValueError` (not a mapping) or pydantic's
    `ValidationError` (a `ValueError`) with the reason."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    return CorrelationConfig.model_validate(raw)
