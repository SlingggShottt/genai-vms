"""Step 1 — temporal grounding: where do the stages of the incident fall in the window?

The model — the trained adapter or the zero-shot base, whichever the registry's `phase_tg` entry
names, with its own fallbacks — is asked a simple question: which stage does each of these frames
show? The spans are derived from the answers (`domain.timeline`). If no model can be reached or
the answer is nonsense, the timeline comes from the detector's own timing, and `fallback_used`
says so."""

from __future__ import annotations

from vms_common.contracts.reasoning import PhaseSpan
from vms_common.llm import ChatResult, Gateway, ImageInput, LLMError, render_prompt
from vms_common.logging import get_logger

from reasoning.adapters.footage import Footage, FootFrame
from reasoning.domain.context import Context, rel
from reasoning.domain.sampling import pick_evenly
from reasoning.domain.timeline import FrameLabels, rule_spans, spans_from_labels

log = get_logger(__name__)

PROMPT_VERSION = "1.0"


def tg_source(result: ChatResult) -> str:
    """Who located the stages, for the report's provenance. The chain is the task's models in the
    registry (the trained adapter, then the plain base, then a cloud model), and the detector's
    timing after that: this says which link answered, and how many before it did not."""
    if result.adapter:
        who = f"adapter:{'/'.join(result.adapter.rstrip('/').split('/')[-2:])}"
    else:
        who = "zero-shot"
    source = f"{who}:{result.provider}/{result.model}"
    if result.fallback_index:
        plural = "s" if result.fallback_index > 1 else ""
        source += f" (after {result.fallback_index} fallback{plural})"
    return source


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
    source = tg_source(result)
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
