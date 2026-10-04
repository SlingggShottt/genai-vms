"""Step 1 — temporal grounding: where do the stages of the incident fall in the window?

The design's TG adapter answers with spans directly. Until it is trained, the zero-shot base
model is asked a simpler question — which stage does each of these frames show? — and the spans
are derived from the answers (`domain.timeline`). If the model cannot be reached or answers
nonsense, the timeline comes from the detector's own timing, and `fallback_used` says so."""

from __future__ import annotations

from vms_common.contracts.reasoning import PhaseSpan
from vms_common.llm import Gateway, ImageInput, LLMError, render_prompt
from vms_common.logging import get_logger

from reasoning.adapters.footage import Footage, FootFrame
from reasoning.domain.context import Context, rel
from reasoning.domain.sampling import pick_evenly
from reasoning.domain.timeline import FrameLabels, rule_spans, spans_from_labels

log = get_logger(__name__)

PROMPT_VERSION = "1.0"


async def locate_phases(
    gateway: Gateway,
    footage: Footage,
    ctx: Context,
    primary_frames: list[FootFrame],
    *,
    n_frames: int,
) -> tuple[list[PhaseSpan], bool, str]:
    """(spans, fallback_used, source)."""
    event_start = min(e.start for e in ctx.events)
    event_end = max(e.end for e in ctx.events)
    rules = rule_spans(
        window_start=ctx.window.start,
        window_end=ctx.window.end,
        event_start=event_start,
        event_end=event_end,
    )
    chosen = pick_evenly(primary_frames, n_frames)
    if len(chosen) < 3:
        return rules, True, "rules"

    try:
        images = [ImageInput(data=await footage.image(f.uri)) for f in chosen]
        prompt = render_prompt(
            "phase_tg",
            PROMPT_VERSION,
            event_type=ctx.event_type.replace("_", " "),
            claim=ctx.claim,
            camera=ctx.primary.camera_id,
            frames=[{"at": rel(f.ts, ctx.window.start)} for f in chosen],
            event_start=rel(event_start, ctx.window.start),
            event_end=rel(event_end, ctx.window.start),
        )
        result = await gateway.vision("phase_tg", prompt, images, response_model=FrameLabels)
    except LLMError as exc:
        log.warning("phase_tg_unavailable", error=str(exc))
        return rules, True, "rules"

    labels = result.parsed
    assert isinstance(labels, FrameLabels)  # noqa: S101 - validated by the gateway
    source = f"zero-shot:{result.provider}/{result.model}"
    spans = spans_from_labels(
        labels.phases,
        [f.ts for f in chosen],
        window_start=ctx.window.start,
        window_end=ctx.window.end,
        source=source,
    )
    if spans is None:
        log.warning("phase_tg_unusable", labels=labels.phases)
        return rules, True, "rules"
    return spans, False, source
