"""What the vision steps do when the model is not there (P7-D5: GPU / language model down).

Stage location falls back to the detector's own timing, and a view that could not be read is left
out instead of being invented or failing the job; the report step has its own test for the same
failure in `test_incident_synthesis.py`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from reasoning.adapters.footage import FootFrame
from reasoning.adapters.store import EventInfo
from reasoning.domain.context import build_context
from reasoning.steps.phases import locate_phases
from reasoning.steps.readings import read_view
from vms_common.contracts.reasoning import PhaseSpan
from vms_common.llm.errors import LLMTimeoutError, LLMUnavailableError
from vms_common.llm.testing import FakeGateway
from vms_common.vqa_bank import load_vqa_bank

T0 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
QUESTIONS = list(
    load_vqa_bank(Path(__file__).resolve().parents[4] / "config" / "vqa_bank.yaml").questions_for(
        "intrusion"
    )
)


class _Footage:
    async def image(self, uri: str) -> bytes:
        return b"jpeg"


def _ctx():
    event = EventInfo(
        id="e1", camera_id="cam02", event_type="intrusion", severity="high",
        rule_id="intrusion.restricted", zone_name=None, start=T0 + timedelta(seconds=10),
        end=T0 + timedelta(seconds=16), status="verified", caption=None, confidence=0.9,
    )  # fmt: skip
    ctx = build_context([event], group_id=None, pad_before_s=10, pad_after_s=10, max_views=2)
    assert ctx is not None
    return ctx


FRAMES = [FootFrame("cam02", T0 + timedelta(seconds=k), f"u{k}") for k in range(27)]


async def test_without_the_model_the_stages_come_from_the_detectors_timing() -> None:
    ctx = _ctx()
    for error in (
        LLMUnavailableError("ollama is not running"),
        LLMTimeoutError("no answer in 90s"),
    ):
        spans, fallback, source = await locate_phases(
            FakeGateway({"phase_tg": [error]}), _Footage(), ctx, FRAMES, n_frames=6
        )
        assert fallback is True and source == "rules"
        assert spans and {s.source for s in spans} == {"rules"}
        # the flagged span is the action, whatever the model would have said
        action = next(s for s in spans if s.phase == "action")
        assert action.start <= T0 + timedelta(seconds=10) + timedelta(seconds=1)
        assert action.end >= T0 + timedelta(seconds=16) - timedelta(seconds=1)


async def test_a_view_the_model_could_not_read_is_left_out_not_invented() -> None:
    ctx = _ctx()
    span = PhaseSpan(
        phase="action", start=T0 + timedelta(seconds=8), end=T0 + timedelta(seconds=12), source="x"
    )
    gateway = FakeGateway({"phase_vr": [LLMUnavailableError("gpu busy")]})
    reading = await read_view(
        gateway, _Footage(), ctx, span, "cam02", FRAMES, QUESTIONS, n_frames=2
    )
    assert reading is None


# ---- which link of the chain located the stages --------------------------------------------

LABELS = '{"phases": ["baseline", "baseline", "precursor", "action", "action", "aftermath"]}'


def _answer(**over):  # noqa: ANN003, ANN202
    """A model's reply to the stage question, as the gateway would hand it back."""
    from reasoning.domain.timeline import FrameLabels  # noqa: PLC0415
    from vms_common.llm import ChatResult  # noqa: PLC0415

    return ChatResult(
        task="phase_tg", text=LABELS, parsed=FrameLabels.model_validate_json(LABELS),
        **{"provider": "ollama", "model": "qwen2.5vl:3b", **over},
    )  # fmt: skip


def test_the_source_names_the_adapter_that_located_the_stages() -> None:
    from reasoning.steps.phases import tg_source  # noqa: PLC0415

    got = tg_source(
        _answer(
            provider="hf_local",
            model="Qwen/Qwen2.5-VL-3B-Instruct",
            adapter="s3://vms-models/tg/v1",
        )
    )
    assert got == "adapter:tg/v1:hf_local/Qwen/Qwen2.5-VL-3B-Instruct"


def test_the_source_of_the_plain_base_is_zero_shot_and_counts_the_links_that_failed() -> None:
    from reasoning.steps.phases import tg_source  # noqa: PLC0415

    assert (
        tg_source(_answer(provider="ollama", model="qwen2.5vl:3b"))
        == "zero-shot:ollama/qwen2.5vl:3b"
    )
    assert (
        tg_source(_answer(provider="ollama", model="qwen2.5vl:3b", fallback_index=1))
        == "zero-shot:ollama/qwen2.5vl:3b (after 1 fallback)"
    )
    assert tg_source(_answer(provider="gemini", model="flash", fallback_index=2)).endswith(
        "(after 2 fallbacks)"
    )


async def test_the_timeline_carries_the_source_of_the_model_that_answered() -> None:
    spans, fallback, source = await locate_phases(
        FakeGateway({"phase_tg": [_answer(provider="hf_local", model="m", adapter="s3://b/tg/v1")]}),
        _Footage(), _ctx(), FRAMES, n_frames=6,
    )  # fmt: skip
    assert fallback is False and source == "adapter:tg/v1:hf_local/m"
    assert spans and {s.source for s in spans} == {source}
