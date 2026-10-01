"""Event rules. Importing this package registers every built-in rule, so
`get_rule` / `registered_rules` always see the full set (CLAUDE.md "New event
rule": add a module here with `@rule("<id>")`, import it below, add its
defaults to `config/rules.yaml`, and write positive + negative tests).
"""

from __future__ import annotations

from events.domain.rules import (
    abandoned_object,
    crowding,
    intrusion_after_hours,
    intrusion_restricted,
    loitering,
    running,
)
from events.domain.rules.base import (
    CameraRule,
    FrameContext,
    Hit,
    Rule,
    RuleParams,
    Severity,
    ZoneRule,
    get_rule,
    registered_rules,
    rule,
)

__all__ = [
    "CameraRule",
    "FrameContext",
    "Hit",
    "Rule",
    "RuleParams",
    "Severity",
    "ZoneRule",
    "abandoned_object",
    "crowding",
    "get_rule",
    "intrusion_after_hours",
    "intrusion_restricted",
    "loitering",
    "registered_rules",
    "rule",
    "running",
]
