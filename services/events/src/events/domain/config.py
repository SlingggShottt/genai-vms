"""Rule configuration — defaults plus per-camera / per-zone overrides
(`config/rules.yaml`, design_architecture.md §7.3, FR-EVT-01 "Thresholds
configurable per camera/zone"). Pure: callers parse the YAML and hand the dict
to `RulesConfig.model_validate`.

Resolution for one (rule, camera, zone):

1. start from the rule's block under `rules:` (or the rule's built-in defaults
   if it isn't listed — an unlisted rule is **enabled**, so a minimal file
   never silently switches a security rule off);
2. apply every matching entry of `overrides:` from least to most specific —
   rule+camera, then rule+zone, then rule+camera+zone — later entries in the
   file winning ties. A `zone` is a zone *name*, as in the twin's
   `FrameObject.zones`;
3. validate the merged params against the rule's own `Params` model.

Everything is validated when the file is loaded (unknown rule ids, unknown
param names, out-of-range values, overrides that name neither camera nor
zone), so a typo fails at startup, not at 3 a.m.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from events.domain.rules import Rule, RuleParams, Severity, get_rule, registered_rules


class RuleConfig(BaseModel):
    """One rule's settings under `rules:`."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    severity: Severity | None = Field(default=None, description="None = the rule's own default")
    verify: bool = Field(
        default=True, description="Run the VLM gate on this rule's candidates (P3-D4; design §7.4)"
    )
    params: dict[str, Any] = Field(default_factory=dict)


class OverrideConfig(BaseModel):
    """An entry of `overrides:` — settings for one camera and/or one zone."""

    model_config = ConfigDict(extra="forbid")

    rule: str
    camera: str | None = None
    zone: str | None = Field(default=None, description="zone name")
    enabled: bool | None = None
    severity: Severity | None = None
    verify: bool | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _must_be_scoped(self) -> OverrideConfig:
        if self.camera is None and self.zone is None:
            raise ValueError(
                f"override for {self.rule!r} must name a camera and/or a zone "
                "(rule-wide settings belong under `rules:`)"
            )
        return self


@dataclass(frozen=True)
class EffectiveRule:
    """A rule's settings after defaults and overrides, for one camera + zone."""

    rule: Rule
    enabled: bool
    severity: Severity
    verify: bool
    params: RuleParams


class RulesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    rules: dict[str, RuleConfig] = Field(default_factory=dict)
    overrides: list[OverrideConfig] = Field(default_factory=list)

    _cache: dict[tuple[str, str, str], EffectiveRule] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _validate_everything_now(self) -> RulesConfig:
        for rule_id in self.rules:
            get_rule(rule_id)  # ValueError (-> ValidationError) naming the known rules
        for override in self.overrides:
            get_rule(override.rule)
        # Resolve every rule's defaults and every override's own scope once, so a
        # bad param name or value surfaces here instead of on the first frame.
        for rule_id in registered_rules():
            self._resolve(rule_id, camera_id="", zone_name="")
        for override in self.overrides:
            self._resolve(
                override.rule, camera_id=override.camera or "", zone_name=override.zone or ""
            )
        return self

    def resolve(self, rule_id: str, camera_id: str, zone_name: str) -> EffectiveRule:
        """Effective settings of `rule_id` for a zone (by name) on a camera."""
        key = (rule_id, camera_id, zone_name)
        effective = self._cache.get(key)
        if effective is None:
            effective = self._resolve(rule_id, camera_id=camera_id, zone_name=zone_name)
            self._cache[key] = effective
        return effective

    def _resolve(self, rule_id: str, *, camera_id: str, zone_name: str) -> EffectiveRule:
        rule = get_rule(rule_id)
        base = self.rules.get(rule_id, RuleConfig())
        enabled, severity, verify = base.enabled, base.severity, base.verify
        params: dict[str, Any] = dict(base.params)

        matching = [
            o
            for o in self.overrides
            if o.rule == rule_id and o.camera in (None, camera_id) and o.zone in (None, zone_name)
        ]
        # camera-only (1) < zone-only (2) < camera+zone (3); stable, so later entries win ties.
        matching.sort(key=lambda o: (o.camera is not None) + 2 * (o.zone is not None))
        for override in matching:
            if override.enabled is not None:
                enabled = override.enabled
            if override.severity is not None:
                severity = override.severity
            if override.verify is not None:
                verify = override.verify
            params.update(override.params)

        return EffectiveRule(
            rule=rule,
            enabled=enabled,
            severity=severity or rule.default_severity,
            verify=verify,
            params=rule.Params.model_validate(params),
        )
