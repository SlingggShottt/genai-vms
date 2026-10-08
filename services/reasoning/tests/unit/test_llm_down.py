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
