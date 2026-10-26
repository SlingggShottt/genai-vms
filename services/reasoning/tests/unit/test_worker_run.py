"""One whole analysis through `ReasoningWorker._run`, with a fake store, fake footage and a
scripted gateway: no database, no model, no network (P5-D4, P5-J4).

What the other worker tests cover in pieces (the failure path, the push messages) is here in one
piece, in order: gather the events, create and attach the report, locate the phases, read every
stage × camera, write the report, keep a copy, store it, announce it. The provenance it stores is
checked, including who located the stages, how long each call took and which views were skipped.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from reasoning.adapters.footage import FootFrame
from reasoning.adapters.store import EventInfo
from reasoning.settings import ReasoningSettings
from reasoning.worker import JobFailedError, ReasoningWorker
from vms_common.llm import ChatResult
from vms_common.llm.errors import LLMUnavailableError
from vms_common.llm.testing import FakeGateway
from vms_common.vqa_bank import load_vqa_bank

T0 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
BANK = load_vqa_bank(Path(__file__).resolve().parents[4] / "config" / "vqa_bank.yaml")
EVENT = EventInfo(
    id="e1", camera_id="cam02", event_type="intrusion", severity="high",
    rule_id="intrusion.restricted", zone_name="yard", start=T0 + timedelta(seconds=15),
    end=T0 + timedelta(seconds=21), status="verified", caption="a person climbs the fence",
    confidence=0.9,
)  # fmt: skip
FRAMES = [
    FootFrame("cam02", T0 + timedelta(seconds=k), f"s3://kf/cam02/{k}.jpg") for k in range(31)
]


class Store:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.completed: dict | None = None

    async def abandon_incidents(self, job_id, reason=None):
        self.calls.append(("abandon", reason))

    async def group_event_ids(self, group_id):
        return []

    async def load_events(self, ids):
        return [EVENT] if "e1" in ids else []

    async def create_incident(self, **kwargs):
        self.calls.append(("create", kwargs["event_type"], kwargs["camera_ids"]))

    async def attach_incident(self, job_id, incident_id):
        self.calls.append(("attach", incident_id))

    async def progress(self, job_id, stage, fraction, *, lease_s):
        self.calls.append(("progress", stage))

    async def complete_incident(self, incident_id, **kwargs):
        self.calls.append(("complete", kwargs["status"]))
        self.completed = kwargs

    async def finish(self, job_id, *, failed=None):
        self.calls.append(("finish", failed))


class Footage:
    def __init__(self, frames=None) -> None:
        self._frames = FRAMES if frames is None else frames
        self.kept: list[tuple[str, str]] = []
        self.put_uris: list[str] = []

    async def frames(self, camera, start, end):
        return self._frames if camera == "cam02" else []

    async def image(self, uri):
        return b"jpeg"

    async def keep(self, uri, dest):
        self.kept.append((uri, dest))

    async def put(self, uri, data, content_type):
        self.put_uris.append(uri)


class Notes:
    def __init__(self) -> None:
        self.sent = []

    async def send(self, message):
        self.sent.append(message)
        return True


def _labels(call) -> dict:
    n = len(call.images)
    stages = ["baseline", "precursor", "action", "action", "aftermath"]
    return {"phases": [stages[min(i * len(stages) // n, len(stages) - 1)] for i in range(n)]}


def _reading(call) -> dict:
    return {"caption": "A person at the fence.", "answers": []}


def _synthesis(call) -> dict:
    """An answer to either of the two synthesis prompts, citing ids that are in the prompt."""
    ids = list(dict.fromkeys(re.findall(r"ev-[a-z]+-\d+", call.prompt)))
    cite = ids[:1]
    if "location" in call.response_model.model_fields:  # the first prompt: stages
        found = re.findall(r"^- (\w+)", call.prompt, flags=re.M)
        return {
            "location": "the yard",
            "conditions": "daylight",
            "actors": [{"ref": "subject", "description": "a person", "evidence": cite}],
            "phases": [
                {"phase": p, "summary": f"the {p} stage", "evidence": cite}
                for p in ("baseline", "precursor", "action", "aftermath")
                if p in call.prompt
            ]
            or [{"phase": "action", "summary": "the action", "evidence": cite}],
            "_unused": found,
        }
    return {
        "title": "Intrusion at the yard fence",
        "summary": "A person climbed the fence.",
        "causal_chain": [{"description": "the person reached the fence", "evidence": cite}],
        "primary": [{"text": "an open approach", "evidence": cite}],
        "environmental": [],
        "security_gaps": [],
        "recommended_actions": [{"action": "add lighting", "priority": "high"}],
        "confidence": 0.7,
        "limitations": [],
    }


def tg_answer(**over) -> ChatResult:  # noqa: ANN003
    from reasoning.domain.timeline import FrameLabels  # noqa: PLC0415

    def make(call):  # noqa: ANN001
        labels = _labels(call)
        return ChatResult(
            task="phase_tg", text="{}", parsed=FrameLabels.model_validate(labels),
            **{"provider": "ollama", "model": "qwen2.5vl:3b", **over},
        )  # fmt: skip

    return make


def rig(*, tg=None, footage=None, frames=None) -> tuple[ReasoningWorker, Store, Footage, Notes]:
    store, foot, notes = Store(), footage or Footage(frames), Notes()
    gateway = FakeGateway(
        {
            "phase_tg": tg or _labels,
            "phase_vr": _reading,
            "incident_synthesis": _synthesis,
        }
    )
    worker = ReasoningWorker(
        settings=ReasoningSettings(pdf_enabled=False),
        store=store, footage=foot, gateway=gateway, bank=BANK, producer=None,
        profile="local", tz=ZoneInfo("Asia/Kolkata"), notifier=notes,
    )  # fmt: skip
    return worker, store, foot, notes


def job() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), group_id=None, event_ids=["e1"], trigger="manual")


async def run(worker: ReasoningWorker, j=None) -> uuid.UUID:
    j = j or job()
    incident = uuid.uuid4()
    worker._incident, worker._attached, worker._fraction = incident, False, 0.0
    await worker._run(j, incident)
    return incident


async def test_a_whole_analysis_runs_in_order_and_stores_a_generated_report() -> None:
    worker, store, foot, notes = rig()

    incident = await run(worker)

    kinds = [c[0] for c in store.calls]
    assert kinds[0] == "abandon" and kinds.index("create") < kinds.index("attach")
    assert kinds.index("attach") < kinds.index("complete") < kinds.index("finish")
    assert store.completed["status"] == "generated"
    assert store.completed["title"] == "Intrusion at the yard fence"
    assert store.calls[kinds.index("finish")] == ("finish", None)
    # the frames the report cites are copied out of the keyframe bucket
    assert foot.kept and all(dest.startswith("s3://vms-evidence/") for _, dest in foot.kept)
    assert foot.put_uris == [f"s3://vms-reports/incidents/{incident}/report.json"]
    # the browsers are told: progress to the end, then the finished report
    types = [m.type for m in notes.sent]
    assert types[-1] == "job.progress" and "incident.ready" in types
    assert notes.sent[-1].data["status"] == "done" and notes.sent[-1].data["incident_id"]


async def test_the_stored_provenance_says_who_located_the_stages_and_how_long_each_call_took() -> (
    None
):
    worker, store, _, _ = rig()

    await run(worker)

    prov = store.completed["provenance"]
    assert prov["tg"] == "zero-shot:fake/fake" and prov["fallback_used"] is False
    timings = prov["timings"]
    steps = [c["step"] for c in timings["calls"]]
    assert steps[0] == "phases" and steps[-1] == "report" and "reading" in steps
    readings = [c for c in timings["calls"] if c["step"] == "reading"]
    assert all({"phase", "camera", "answered", "frames", "seconds"} <= set(c) for c in readings)
    assert all(c["answered"] and c["frames"] >= 1 for c in readings)
    assert timings["views_skipped"] == 0
    assert set(timings["seconds_by_step"]) == {"phases", "reading", "report"}
    assert timings["calls"][0]["source"] == prov["tg"]


async def test_when_the_adapter_answers_the_provenance_names_it() -> None:
    worker, store, _, _ = rig(
        tg=tg_answer(
            provider="hf_local",
            model="Qwen/Qwen2.5-VL-3B-Instruct",
            adapter="s3://vms-models/tg/v1",
        )
    )

    await run(worker)

    assert store.completed["provenance"]["tg"].startswith("adapter:tg/v1:hf_local/")


async def test_when_no_model_answers_the_detectors_timing_is_used_and_recorded() -> None:
    worker, store, _, _ = rig(tg=LLMUnavailableError("ollama is not running"))

    await run(worker)

    prov = store.completed["provenance"]
    assert prov["tg"] == "rules" and prov["fallback_used"] is True
    assert prov["timings"]["calls"][0]["fallback"] is True


async def test_a_view_with_no_usable_frame_is_skipped_and_counted_not_invented() -> None:
    # frames only around the flagged event: the early stages of the window have none, and no frame
    # lies within four seconds of them, so those views are skipped
    late = [f for f in FRAMES if f.ts >= T0 + timedelta(seconds=14)]
    worker, store, _, _ = rig(frames=late)

    await run(worker)

    timings = store.completed["provenance"]["timings"]
    skipped = [c for c in timings["calls"] if c["step"] == "reading" and not c["answered"]]
    assert skipped, "the early stages have no frame within four seconds, so they are skipped"
    assert timings["views_skipped"] == len(skipped)
    assert all(c["frames"] == 0 for c in skipped)
    assert any(c["answered"] for c in timings["calls"] if c["step"] == "reading")


async def test_footage_that_is_gone_fails_the_job_with_a_reason_before_any_model_is_asked() -> None:
    worker, store, _, _ = rig(frames=[])

    with pytest.raises(JobFailedError, match="no longer available"):
        await run(worker)

    assert ("complete", "generated") not in store.calls
    assert not worker._gateway.calls_for("phase_tg")  # type: ignore[attr-defined]
