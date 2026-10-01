"""Rule abstraction and registry (design_architecture.md §7.3, CLAUDE.md
"New event rule": `@rule("<id>")` + a params schema).

A rule answers one narrow question about *one sampled frame* and *one zone*:
"which things in this zone satisfy my condition right now?" — a list of
`Hit`s. Everything temporal (needs to hold for N frames / T seconds,
debouncing, extending an open candidate across segments) is the engine's job
(`events.domain.engine`), driven by the thresholds each rule's params expose
through `required_frames()` / `required_duration_s()` / `debounce_s`. That
keeps each rule a few lines of pure logic that is trivial to test.

Pure — no I/O.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from typing import ClassVar, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from vms_common.contracts.twin import FrameObject
from vms_common.contracts.zones import ZoneInternal

Severity = Literal["low", "medium", "high", "critical"]
ZoneType = Literal["generic", "restricted", "entrance", "exit"]
ALL_ZONE_TYPES: tuple[ZoneType, ...] = ("generic", "restricted", "entrance", "exit")

# What counts as a "vehicle" for intrusion (design §7.3: person/vehicle).
VEHICLE_CATEGORIES = ("bicycle", "car", "motorcycle", "bus", "truck")


class RuleParams(BaseModel):
    """Parameters common to every rule; subclasses add their own.

    `extra="forbid"`: a misspelt key in `config/rules.yaml` must fail at load
    time, not silently fall back to a default.
    """

    model_config = ConfigDict(extra="forbid")

    debounce_s: float = Field(
        default=5.0,
        ge=0,
        description="Longest gap (s) between two hits that still belong to one candidate.",
    )

    def required_frames(self) -> int:
        """Hit frames needed before an episode becomes a candidate."""
        return 1

    def required_duration_s(self) -> float:
        """Time (s) an episode must have lasted before it becomes a candidate."""
        return 0.0


@dataclass(frozen=True)
class FrameContext:
    """What a rule may know about the frame being evaluated."""

    camera_id: str
    ts: datetime  # timezone-aware
    site_tz: tzinfo

    @property
    def local_time(self) -> datetime:
        """Frame time in the site's local timezone (zone schedules are site-local)."""
        return self.ts.astimezone(self.site_tz)


@dataclass(frozen=True)
class Hit:
    """One thing satisfying a rule's condition in one frame and zone.

    `key` identifies the episode within (camera, rule, zone) — the track id for
    per-track rules, `"*"` for a whole-zone condition such as crowding.
    `metrics` are numbers whose per-episode peak the engine keeps (e.g. the
    head count), stored under `peak_<name>` in the candidate's details.
    """

    key: str
    track_ids: tuple[str, ...]
    score: float
    metrics: dict[str, float] = field(default_factory=dict)


class Rule(ABC):
    """One event rule. Subclass, set the class attributes, register with `@rule`."""

    id: ClassVar[str]
    event_type: ClassVar[str]
    default_severity: ClassVar[Severity]
    Params: ClassVar[type[RuleParams]]

    @abstractmethod
    def evaluate(
        self,
        zone: ZoneInternal,
        objects: Sequence[FrameObject],
        params: RuleParams,
        ctx: FrameContext,
    ) -> list[Hit]:
        """Hits in `zone` for this frame. `objects` is everything the twin puts in
        this zone in this frame (any category) — filter by `params` yourself.
        Return `[]` when the rule doesn't apply to this zone."""


_REGISTRY: dict[str, Rule] = {}


RuleClassT = TypeVar("RuleClassT", bound=type[Rule])


def rule(rule_id: str) -> Callable[[RuleClassT], RuleClassT]:
    """Register a `Rule` subclass under `rule_id` (the id used in `rules.yaml`,
    `events.candidates.rule_id` and `event.v1`)."""

    def register(cls: RuleClassT) -> RuleClassT:
        if rule_id in _REGISTRY:
            raise ValueError(f"rule id {rule_id!r} is already registered")
        cls.id = rule_id
        _REGISTRY[rule_id] = cls()
        return cls

    return register


def get_rule(rule_id: str) -> Rule:
    try:
        return _REGISTRY[rule_id]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise ValueError(f"unknown rule id {rule_id!r}; known rules: {known}") from None


def registered_rules() -> dict[str, Rule]:
    """A copy of the registry, keyed by rule id."""
    return dict(_REGISTRY)
