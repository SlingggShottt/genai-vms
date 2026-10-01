"""Rule abstraction and registry (design_architecture.md §7.3, CLAUDE.md
"New event rule": `@rule("<id>")` + a params schema).

A rule answers one narrow question about *one sampled frame*: "which things
satisfy my condition right now?" — a list of `Hit`s. There are two kinds:

* a `ZoneRule` is asked once per zone that has objects in it, and judges only
  those objects (intrusion, loitering, crowding);
* a `CameraRule` is asked once per frame about the whole view, with a small
  persistent `memory` it may use to remember things between frames (`running`,
  `abandoned_object`).

Everything temporal (needs to hold for N frames / T seconds, debouncing,
extending an open candidate across segments) is the engine's job
(`events.domain.engine`), driven by the thresholds each rule's params expose
through `required_frames()` / `required_duration_s()` / `debounce_s`. A rule that
tracks its own timing in `memory` simply reports a hit once its condition holds
and tells the engine when that condition began (`Hit.since`). That keeps each
rule a few lines of pure logic that is trivial to test.

Pure — no I/O.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from typing import Any, ClassVar, Literal, TypeVar

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
    `since`, if set, is when the condition began — earlier than this frame for a
    rule that only reports a hit once it has held for a while (an object left
    unattended); the candidate then starts there instead of at the first hit.
    """

    key: str
    track_ids: tuple[str, ...]
    score: float
    metrics: dict[str, float] = field(default_factory=dict)
    since: datetime | None = None


Scope = Literal["zone", "camera"]


class Rule(ABC):
    """Common shape of an event rule. Subclass `ZoneRule` or `CameraRule`, set the
    class attributes and register it with `@rule("<id>")`."""

    id: ClassVar[str]
    event_type: ClassVar[str]
    default_severity: ClassVar[Severity]
    Params: ClassVar[type[RuleParams]]
    scope: ClassVar[Scope]


class ZoneRule(Rule):
    """A rule about the things inside one zone."""

    scope: ClassVar[Scope] = "zone"

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


class CameraRule(Rule):
    """A rule about the whole camera view, independent of zones (so it works on a
    camera with no zones configured). Candidates have no zone."""

    scope: ClassVar[Scope] = "camera"

    @abstractmethod
    def evaluate_camera(
        self,
        objects: Sequence[FrameObject],
        params: RuleParams,
        ctx: FrameContext,
        memory: dict[str, Any],
    ) -> list[Hit]:
        """Hits for this frame, given every object in it.

        Called for every sampled frame (also when `objects` is empty, so time can
        pass). `memory` is this rule's scratchpad for this camera: it is saved with
        the camera's state and handed back on the next frame, even after a restart,
        so it must stay JSON-serialisable (string keys; numbers, strings, lists,
        dicts, None). Drop entries you no longer need — nothing else will."""


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
