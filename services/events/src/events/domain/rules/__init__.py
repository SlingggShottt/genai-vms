"""Event rules. Importing this package registers every built-in rule, so
`get_rule` / `registered_rules` always see the full set (CLAUDE.md "New event
rule": add a module here with `@rule("<id>")`, import it below, add its
defaults to `config/rules.yaml`, and write positive + negative tests).
"""

from __future__ import annotations

from events.domain.rules import crowding, intrusion_after_hours, intrusion_restricted, loitering
from events.domain.rules.base import (
    FrameContext,
    Hit,
    Rule,
    RuleParams,
    Severity,
    get_rule,
    registered_rules,
    rule,
)

__all__ = [
    "FrameContext",
    "Hit",
    "Rule",
    "RuleParams",
    "Severity",
    "crowding",
    "get_rule",
    "intrusion_after_hours",
    "intrusion_restricted",
    "loitering",
    "registered_rules",
    "rule",
]
