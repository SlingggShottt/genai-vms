"""Assembling `evidence.v1` and rendering it as prompt text. Pure: ids are assigned here, once,
in a fixed order, so the same readings always produce the same bundle."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from vms_common.contracts.event import Severity
from vms_common.contracts.reasoning import (
    EvidenceBundleV1,
    EvidenceCaption,
    EvidenceEvent,
    EvidenceFrame,
    EvidencePhase,
    EvidenceQA,
    EvidenceView,
    PhaseName,
    PhaseSpan,
    Window,
)


@dataclass
class ViewReading:
    camera_id: str
    caption: str
    answers: list[tuple[str, str, str]] = field(default_factory=list)  # (question id, q, a)
    frames: list[tuple[str, datetime]] = field(default_factory=list)  # (uri, ts)


@dataclass
class PhaseReading:
    phase: PhaseName
    views: list[ViewReading]


class IdCounter:
    def __init__(self) -> None:
        self._n: dict[str, int] = {}

    def next(self, kind: str) -> str:
        self._n[kind] = self._n.get(kind, 0) + 1
        return f"ev-{kind}-{self._n[kind]:02d}"


def build_bundle(
    *,
    group_id: str | None,
    event_type: str,
    severity: Severity,
    cameras: list[str],
    primary_camera: str,
    window: Window,
    timeline: list[PhaseSpan],
    readings: list[PhaseReading],
    events: list[tuple[str, str, str, str | None]],  # (id, camera, type, caption)
    provenance: dict[str, object],
) -> EvidenceBundleV1:
    ids = IdCounter()
    event_items = [
        EvidenceEvent(id=ids.next("evt"), camera_id=c, event_type=t, caption=cap)
        for _eid, c, t, cap in events
    ]
    phases: list[EvidencePhase] = []
    for pr in readings:
        views: list[EvidenceView] = []
        for v in pr.views:
            if not v.caption.strip() and not v.frames:
                continue  # skip empty views (§8: "skips empty phases/views")
            views.append(
                EvidenceView(
                    camera_id=v.camera_id,
                    caption=EvidenceCaption(id=ids.next("cap"), text=v.caption.strip()),
                    vqa=[EvidenceQA(id=ids.next("qa"), q=q, a=a) for _qid, q, a in v.answers],
                    frames=[EvidenceFrame(id=ids.next("fr"), uri=u, ts=t) for u, t in v.frames],
                )
            )
        if views:
            phases.append(EvidencePhase(phase=pr.phase, views=views))
    return EvidenceBundleV1(
        group_id=group_id,
        event_type=event_type,
        severity=severity,
        cameras=cameras,
        primary_camera=primary_camera,
        window=window,
        phase_timeline=timeline,
        phases=phases,
        events=event_items,
        provenance=provenance,
    )


def _clock(ts: datetime, tz: ZoneInfo) -> str:
    return ts.astimezone(tz).strftime("%H:%M:%S")


def render_events(bundle: EvidenceBundleV1) -> str:
    if not bundle.events:
        return "(none)"
    return "\n".join(
        f"[{e.id}] {e.event_type} on {e.camera_id}" + (f': "{e.caption}"' if e.caption else "")
        for e in bundle.events
    )


def render_evidence(bundle: EvidenceBundleV1, tz: ZoneInfo, *, with_frames: bool = True) -> str:
    spans = {p.phase: p for p in bundle.phase_timeline}
    out: list[str] = []
    for ph in bundle.phases:
        span = spans.get(ph.phase)
        when = f" ({_clock(span.start, tz)}–{_clock(span.end, tz)})" if span else ""
        out.append(f"Stage {ph.phase}{when}")
        for v in ph.views:
            out.append(f"  camera {v.camera_id}:")
            out.append(f'    [{v.caption.id}] caption: "{v.caption.text}"')
            for qa in v.vqa:
                out.append(f"    [{qa.id}] {qa.q} -> {qa.a}")
            if with_frames and v.frames:
                out.append("    frames: " + " ".join(f"[{f.id}]" for f in v.frames))
    return "\n".join(out) or "(no evidence could be collected)"
