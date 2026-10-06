"""Step 2 — evidence: for each stage × camera, show the frames of that stage and ask for a
caption plus the event type's questions from the VQA bank. The adapter-trained PhaVR model is
the intended reader; today the zero-shot base answers, and its provenance says so."""

from __future__ import annotations

from pydantic import BaseModel, Field
from vms_common.contracts.reasoning import PhaseSpan
from vms_common.llm import Gateway, ImageInput, LLMError, render_prompt
from vms_common.logging import get_logger
from vms_common.vqa_bank import VQAQuestion

from reasoning.adapters.footage import Footage, FootFrame
from reasoning.domain.context import Context, rel
from reasoning.domain.evidence import ViewReading
from reasoning.domain.sampling import nearest, pick_evenly, within
from reasoning.domain.timeline import PHASE_MEANING

log = get_logger(__name__)

PROMPT_VERSION = "1.0"


class _Answer(BaseModel):
    id: str
    answer: str


class ViewDraft(BaseModel):
    caption: str = Field(min_length=1)
    answers: list[_Answer] = Field(default_factory=list)


def clean_answers(draft: ViewDraft, questions: list[VQAQuestion]) -> list[tuple[str, str, str]]:
    """Keep only answers to questions that were asked, in the allowed vocabulary (matched
    case-insensitively, returned in its canonical spelling). Anything else is dropped rather
    than repaired: an answer we cannot map is not evidence."""
    asked = {q.id: q for q in questions}
    seen: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for a in draft.answers:
        q = asked.get(a.id.strip())
        if q is None or q.id in seen:
            continue
        canon = {x.lower(): x for x in q.answers}
        value = canon.get(a.answer.strip().lower().rstrip("."))
        if value is None:
            continue
        seen.add(q.id)
        out.append((q.id, q.text, value))
    return out


async def read_view(
    gateway: Gateway,
    footage: Footage,
    ctx: Context,
    span: PhaseSpan,
    camera: str,
    camera_frames: list[FootFrame],
    questions: list[VQAQuestion],
    *,
    n_frames: int,
) -> ViewReading | None:
    inside = within(camera_frames, span.start, span.end, lambda f: f.ts)
    if inside:
        chosen = pick_evenly(inside, n_frames)
    else:
        # A stage shorter than the 2 s sampling interval may hold no frame; the nearest one
        # still shows the scene at that moment.
        mid = span.start + (span.end - span.start) / 2
        chosen = nearest(camera_frames, mid, 1, lambda f: f.ts)
        if not chosen or abs((chosen[0].ts - mid).total_seconds()) > 4.0:
            return None

    try:
        images = [ImageInput(data=await footage.image(f.uri)) for f in chosen]
        prompt = render_prompt(
            "phase_vr",
            PROMPT_VERSION,
            event_type=ctx.event_type.replace("_", " "),
            phase=span.phase,
            phase_meaning=PHASE_MEANING[span.phase],
            camera=camera,
            n_frames=len(chosen),
            times=[rel(f.ts, ctx.window.start) for f in chosen],
            questions=[{"id": q.id, "text": q.text, "answers": list(q.answers)} for q in questions],
        )
        result = await gateway.vision("phase_vr", prompt, images, response_model=ViewDraft)
    except LLMError as exc:
        log.warning("phase_vr_failed", phase=span.phase, camera=camera, error=str(exc))
        return None

    draft = result.parsed
    assert isinstance(draft, ViewDraft)  # noqa: S101 - validated by the gateway
    return ViewReading(
        camera_id=camera,
        caption=draft.caption.strip(),
        answers=clean_answers(draft, questions),
        frames=[(f.uri, f.ts) for f in chosen],
    )
