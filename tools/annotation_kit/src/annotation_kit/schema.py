"""The data formats of the kit.

Three, each owned by someone different:

- `PhaseLabelClip` is one line of the phase annotation export (`phase_labels.jsonl`), which is what
  Track D's annotation kit (P3-D5) hands over. Its shape is a *proposal* until D5 freezes it
  (`ml/annotation/phase_export_example.json`); the kit builds against that example.
- `CaptionVqaTask` is what is put into Label Studio: one phase of one clip in one camera's view.
- `PhavrLabel` is what comes out (`phavr_labels.jsonl`, `phavr_label.v1`): the verified caption and
  VQA answers, with the model's draft kept beside them so the edit rate can be measured and so a
  reader can see what a person changed. The PhaVR dataset builder (P5-J1) reads this.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from annotation_kit.phases import PHASES

Phase = Literal["baseline", "precursor", "escalation", "action", "aftermath"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- in: the phase annotation export -----------------------------------------------------------


class PhaseSpan(_Strict):
    phase: Phase
    start_s: float = Field(ge=0)
    end_s: float

    @model_validator(mode="after")
    def _ends_after_it_starts(self) -> Self:
        if self.end_s <= self.start_s:
            raise ValueError(
                f"{self.phase}: end_s ({self.end_s}) must be after start_s ({self.start_s})"
            )
        return self


class ClipView(_Strict):
    camera: str = Field(min_length=1)
    video_uri: str = Field(min_length=1)


class PhaseLabelClip(_Strict):
    """One phase-annotated incident clip. A phase with nothing in it is simply left out."""

    schema_version: Literal["phase_labels.v1"] = "phase_labels.v1"
    clip_id: str = Field(min_length=1)
    source_video: str = Field(min_length=1)  # train/val/test are split by this, never by clip
    event_type: str = Field(min_length=1)
    primary_view: str
    views: list[ClipView] = Field(min_length=1)
    phases: list[PhaseSpan] = Field(min_length=1)
    annotator: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        cameras = [view.camera for view in self.views]
        if len(set(cameras)) != len(cameras):
            raise ValueError(f"{self.clip_id}: a camera appears twice in views")
        if self.primary_view not in cameras:
            raise ValueError(
                f"{self.clip_id}: primary_view {self.primary_view!r} is not one of the views"
            )
        order = [PHASES.index(span.phase) for span in self.phases]
        if order != sorted(set(order)):
            raise ValueError(f"{self.clip_id}: phases must be in order, each at most once")
        for before, after in zip(self.phases, self.phases[1:], strict=False):
            if after.start_s < before.end_s:
                raise ValueError(f"{self.clip_id}: {after.phase} starts before {before.phase} ends")
        return self


# ---- the Label Studio task ---------------------------------------------------------------------


class CaptionVqaTask(_Strict):
    """One phase of one clip in one view: what an annotator verifies in one sitting."""

    clip_id: str
    source_video: str
    event_type: str
    view: str
    phase: Phase
    start_s: float
    end_s: float
    video_uri: str  # the clip, for the model to read
    video: str  # the same, with a #t=start,end media fragment, for Label Studio's player

    @property
    def key(self) -> str:
        """Stable across re-exports: how a label is matched back to its draft."""
        return f"{self.clip_id}|{self.view}|{self.phase}"


# ---- out: phavr_labels.jsonl -------------------------------------------------------------------


class VqaItem(_Strict):
    id: str
    q: str
    a: str


class PseudoLabel(_Strict):
    """What the model drafted before a person looked."""

    model_version: str
    caption: str
    vqa: dict[str, str]  # question id -> answer


class Edits(_Strict):
    """How far the verified label is from the draft. Only meaningful when there was a draft."""

    caption_changed: bool
    caption_similarity: float = Field(ge=0, le=1)  # 1.0 = identical
    answers_changed: list[str]  # question ids whose answer a person changed


class PhavrLabel(_Strict):
    schema_version: Literal["phavr_label.v1"] = "phavr_label.v1"
    clip_id: str
    source_video: str
    event_type: str
    view: str
    phase: Phase
    start_s: float
    end_s: float
    caption: str
    vqa: list[VqaItem]
    pseudo: PseudoLabel | None
    edits: Edits | None
    annotator: str | None

    @model_validator(mode="after")
    def _a_draft_and_its_edits_go_together(self) -> Self:
        if (self.pseudo is None) != (self.edits is None):
            raise ValueError("pseudo and edits must both be present, or both absent")
        return self
