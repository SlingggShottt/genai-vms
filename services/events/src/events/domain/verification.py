"""The VLM verification gate's decisions — pure (design_architecture.md §7.4, P3-D4).

What the model said is a `Verdict`; what to do about it is `decide`; what to do when there is no
model to ask is `unavailable_action`. Nothing here talks to the model, the database or Kafka.

The rules, as the design gives them (§7.4) with the choices it leaves open made explicit:

* `yes` at confidence >= `min_confidence` -> **verified**; `no` -> **rejected** (kept, with why).
* `yes` below `min_confidence` is not trusted and counts as `unsure`.
* `unsure` -> **verified, flagged** for a rule whose severity is at or below
  `unsure_accepted_up_to` (default `low`: a doubtful "someone ran" is still worth recording),
  **rejected** above it (a doubtful intrusion is not an alert).
* A reply that never validates is `unsure` with no confidence (the gateway already re-asked).
* No answer at all (gateway down, no keyframes to show): a candidate at or above `hold_from`
  (default `medium`, the severity that raises alerts) **waits** and is tried again, so a model
  outage delays an alert rather than dropping it or raising it unchecked; lower severities, and
  anything that has waited `hold_max_age_s`, are published as **skipped** (unverified, said so).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from vms_common.contracts.event import SEVERITY_ORDER, Severity, severity_rank

from events.domain.evidence import EvidenceFrame, spread

TASK = "event_verify"
PROMPT_VERSION = "1.0"
MAX_FRAMES = 4  # the task's `max_images` in config/models.yaml

VerdictValue = Literal["yes", "no", "unsure"]
GateStatus = Literal["verified", "skipped", "rejected"]
Unavailable = Literal["hold", "skip"]


class Verdict(BaseModel):
    """The model's answer (design §7.4): `{"verdict": "yes|no|unsure", "confidence": 0-1,
    "caption": "..."}`. Extra keys are ignored: small models like to add some."""

    model_config = ConfigDict(extra="ignore")

    verdict: VerdictValue
    confidence: float = Field(ge=0, le=1)
    caption: str = Field(default="", max_length=600)

    @field_validator("verdict", mode="before")
    @classmethod
    def _tolerate_case_and_padding(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("caption", mode="before")
    @classmethod
    def _caption_is_text(cls, value: object) -> object:
        return "" if value is None else value

    @field_validator("caption")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


@dataclass(frozen=True)
class GatePolicy:
    min_confidence: float = 0.6
    unsure_accepted_up_to: Severity = "low"
    hold_from: Severity = "medium"
    hold_max_age_s: float = 600.0

    def __post_init__(self) -> None:
        if not 0 <= self.min_confidence <= 1:
            raise ValueError("min_confidence must be between 0 and 1")
        if self.hold_max_age_s < 0:
            raise ValueError("hold_max_age_s must not be negative")
        for name in ("unsure_accepted_up_to", "hold_from"):
            if getattr(self, name) not in SEVERITY_ORDER:
                raise ValueError(f"{name} must be one of {', '.join(SEVERITY_ORDER)}")


@dataclass(frozen=True)
class Decision:
    status: Literal["verified", "rejected"]
    reason: str
    flagged: bool = False  # verified although the model was unsure


def decide(verdict: Verdict, severity: str, policy: GatePolicy) -> Decision:
    """What the gate concludes from a model's answer about a candidate of `severity`."""
    if verdict.verdict == "no":
        return Decision("rejected", "the model said this is not happening")
    if verdict.verdict == "yes" and verdict.confidence >= policy.min_confidence:
        return Decision("verified", "the model confirmed it")

    why = "the model was unsure"
    if verdict.verdict == "yes":
        why = (
            f"the model said yes at confidence {verdict.confidence:.2f}, "
            f"below {policy.min_confidence:.2f}"
        )
    if severity_rank(severity) <= severity_rank(policy.unsure_accepted_up_to):
        return Decision("verified", f"{why}; accepted for a {severity}-severity rule", flagged=True)
    return Decision("rejected", f"{why}; not accepted for a {severity}-severity rule")


def unavailable_action(severity: str, waited_s: float, policy: GatePolicy) -> Unavailable:
    """`hold` (try again later) or `skip` (publish unverified) for a candidate nobody could
    check, which has already waited `waited_s`."""
    if severity_rank(severity) < severity_rank(policy.hold_from):
        return "skip"
    return "hold" if waited_s < policy.hold_max_age_s else "skip"


def retry_delay_s(attempts: int, *, base_s: float = 5.0, cap_s: float = 300.0) -> float:
    """Seconds to wait after the `attempts`-th failed try: base, 2x base, 4x ... up to `cap_s`."""
    return min(cap_s, base_s * 2 ** max(0, attempts - 1))


def select_frames(evidence: list[EvidenceFrame], k: int = MAX_FRAMES) -> list[EvidenceFrame]:
    """At most `k` of a candidate's evidence frames, in time order, spanning it (the first and
    the latest are always included)."""
    return spread(sorted(evidence, key=lambda frame: frame.ts), k)


def offsets_s(frames: list[EvidenceFrame]) -> list[int]:
    """Seconds from the first frame to each, rounded: what the prompt tells the model."""
    return [round((frame.ts - frames[0].ts).total_seconds()) for frame in frames] if frames else []


def verification_record(
    status: GateStatus,
    reason: str,
    *,
    verdict: Verdict | None = None,
    flagged: bool = False,
    model: str | None = None,
    latency_ms: int | None = None,
    frames: int = 0,
    attempts: int = 0,
    prompt_version: str | None = None,
) -> dict[str, Any]:
    """What `events.events.verification` stores: the outcome with everything that explains it.
    `confidence` and `caption` are the model's, so they are absent when it was not asked."""
    return {
        "status": status,
        "reason": reason,
        "verdict": verdict.verdict if verdict else None,
        "confidence": verdict.confidence if verdict else None,
        "caption": (verdict.caption or None) if verdict else None,
        "flagged": flagged,
        "model": model,
        "latency_ms": latency_ms,
        "frames": frames,
        "attempts": attempts,
        "prompt_version": prompt_version,
    }
