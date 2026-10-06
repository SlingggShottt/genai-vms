"""phasetimeline.v1, evidence.v1, incident.v1 and incidentready.v1 (design_architecture.md §8).

The reasoning service produces all four: a phase timeline over the correlated window, an
evidence bundle (captions + VQA per phase × view, with stable ids), the incident report that
cites those ids, and the Kafka notice that a report is ready. The api and the UI read the
JSON forms stored in `reasoning.incidents`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from vms_common.contracts.base import MessageEnvelope
from vms_common.contracts.event import Severity

PhaseName = Literal["baseline", "precursor", "escalation", "action", "aftermath"]
PHASES: tuple[PhaseName, ...] = ("baseline", "precursor", "escalation", "action", "aftermath")


class Window(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: AwareDatetime
    end: AwareDatetime


class PhaseSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: PhaseName
    start: AwareDatetime
    end: AwareDatetime
    source: str = Field(description="who drew this boundary, e.g. 'zero-shot:qwen2.5vl:3b'")


class PhaseTimelineV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["phasetimeline.v1"] = "phasetimeline.v1"
    group_id: str | None = None
    event_type: str
    primary_camera: str
    window: Window
    phases: list[PhaseSpan]
    fallback_used: bool = False


# --- evidence.v1 -----------------------------------------------------------------------------


class EvidenceFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    uri: str
    ts: AwareDatetime


class EvidenceCaption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str


class EvidenceQA(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    q: str
    a: str


class EvidenceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera_id: str
    caption: EvidenceCaption
    vqa: list[EvidenceQA] = Field(default_factory=list)
    frames: list[EvidenceFrame] = Field(default_factory=list)


class EvidencePhase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: PhaseName
    views: list[EvidenceView] = Field(default_factory=list)


class EvidenceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    camera_id: str
    event_type: str
    caption: str | None = None


class EvidenceBundleV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["evidence.v1"] = "evidence.v1"
    group_id: str | None = None
    event_type: str
    severity: Severity
    cameras: list[str]
    primary_camera: str
    window: Window
    phase_timeline: list[PhaseSpan]
    phases: list[EvidencePhase]
    events: list[EvidenceEvent] = Field(default_factory=list)
    provenance: dict[str, object] = Field(default_factory=dict)

    def evidence_ids(self) -> set[str]:
        """Every id an incident report may cite."""
        ids: set[str] = {e.id for e in self.events}
        for phase in self.phases:
            for view in phase.views:
                ids.add(view.caption.id)
                ids.update(q.id for q in view.vqa)
                ids.update(f.id for f in view.frames)
        return ids


# --- incident.v1 -----------------------------------------------------------------------------


class Actor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str
    description: str
    evidence: list[str] = Field(default_factory=list)


class SceneUnderstanding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str
    conditions: str
    actors: list[Actor] = Field(default_factory=list)


class PhaseSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: PhaseName
    summary: str
    evidence: list[str] = Field(default_factory=list)


class CausalStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int = Field(ge=1)
    description: str
    evidence: list[str] = Field(default_factory=list)


class Factor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    evidence: list[str] = Field(default_factory=list)


class ContributingFactors(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: list[Factor] = Field(default_factory=list)
    environmental: list[Factor] = Field(default_factory=list)
    security_gaps: list[Factor] = Field(default_factory=list)


class RecommendedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    priority: Literal["low", "medium", "high"] = "medium"
    owner_role: str = "supervisor"


class IncidentReportV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["incident.v1"] = "incident.v1"
    incident_id: str
    group_id: str | None = None
    title: str
    summary: str = Field(description="two or three sentences an operator can read in ten seconds")
    event_type: str
    severity: Severity
    window: Window
    cameras: list[str]
    scene_understanding: SceneUnderstanding
    phase_analysis: list[PhaseSummary]
    causal_chain: list[CausalStep]
    contributing_factors: ContributingFactors
    recommended_actions: list[RecommendedAction]
    confidence: float = Field(ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)
    evidence_index: list[str] = Field(default_factory=list)
    provenance: dict[str, object] = Field(default_factory=dict)

    def cited_ids(self) -> set[str]:
        ids: set[str] = set()
        for actor in self.scene_understanding.actors:
            ids.update(actor.evidence)
        for p in self.phase_analysis:
            ids.update(p.evidence)
        for s in self.causal_chain:
            ids.update(s.evidence)
        for group in (
            self.contributing_factors.primary,
            self.contributing_factors.environmental,
            self.contributing_factors.security_gaps,
        ):
            for f in group:
                ids.update(f.evidence)
        return ids


class IncidentReadyV1(MessageEnvelope):
    schema_version: Literal["incidentready.v1"] = "incidentready.v1"

    incident_id: str
    group_id: str | None = None
    status: Literal["generated", "failed"]
    severity: Severity
    title: str
