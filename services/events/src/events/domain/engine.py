"""The rule engine: one digital twin in, candidate updates out — pure.

`process_twin` replays a twin's sampled frames through every enabled rule and
folds the per-frame hits into **episodes** (`events.domain.state`):

* A hit extends the matching open episode if it follows the previous hit within
  the rule's `debounce_s`; otherwise it closes that episode and starts a new
  one. This is the debounce — a detection flicker or a short occlusion doesn't
  split one loitering stay into three candidates.
* An episode becomes a **candidate** once it has at least the rule's
  `required_frames()` hits spanning at least `required_duration_s()` (e.g. a
  person in a zone for 60 s -> loitering). From then on every segment that
  extends it yields an `open` update with the new end time; once the condition
  has been quiet for `debounce_s` it yields a final `closed` update.
* Episodes that never reach their thresholds are dropped without a trace.

State is passed in and returned (never mutated), so the caller can write the
candidates to the database first and only then checkpoint the state: a crash in
between replays the twin against the old state and produces the same
deterministic candidate ids (design §15 idempotency).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import tzinfo

from vms_common.contracts.twin import Frame, FrameObject, TwinV1
from vms_common.contracts.zones import ZoneInternal

from events.domain.candidates import CandidateStatus, CandidateUpdate, candidate_id
from events.domain.config import EffectiveRule, RulesConfig
from events.domain.evidence import add_evidence, frame_evidence
from events.domain.rules import CameraRule, FrameContext, Hit, ZoneRule, registered_rules
from events.domain.state import CameraState, Episode


@dataclass(frozen=True)
class TwinOutcome:
    """Result of processing one twin."""

    state: CameraState
    updates: list[CandidateUpdate]
    skipped: bool = False  # the twin was a replay / out of order; nothing was applied


def process_twin(
    state: CameraState,
    twin: TwinV1,
    *,
    zones: Sequence[ZoneInternal],
    config: RulesConfig,
    site_tz: tzinfo,
) -> TwinOutcome:
    """Apply one twin to `state`. `site_tz` is the site's timezone (zone schedules are
    site-local). `state` is not modified; the new state is in the outcome."""
    if state.camera_id != twin.camera_id:
        raise ValueError(f"state is for {state.camera_id!r}, twin is for {twin.camera_id!r}")
    if state.last_segment_end is not None and twin.end_ts <= state.last_segment_end:
        # Already applied (a replay after a crash) or older than what we've seen:
        # the state can't go backwards, and its candidates were written when it advanced.
        return TwinOutcome(state=state, updates=[], skipped=True)

    work = state.model_copy(deep=True)
    zones_by_name = {z.name: z for z in zones if z.camera_id == twin.camera_id}
    zone_rules = {rid: r for rid, r in registered_rules().items() if isinstance(r, ZoneRule)}
    camera_rules = {rid: r for rid, r in registered_rules().items() if isinstance(r, CameraRule)}
    touched: set[str] = set()
    closed: list[CandidateUpdate] = []

    for frame in sorted(twin.frames, key=lambda f: f.ts):
        ctx = FrameContext(camera_id=twin.camera_id, ts=frame.ts, site_tz=site_tz)
        for zone_name, objects in _objects_by_zone(frame.objects, zones_by_name).items():
            zone = zones_by_name[zone_name]
            for rule_id, rule in zone_rules.items():
                effective = config.resolve(rule_id, twin.camera_id, zone_name)
                if not effective.enabled:
                    continue
                for hit in rule.evaluate(zone, objects, effective.params, ctx):
                    _record_hit(work, hit, effective, zone, frame, twin, closed, touched)

        # Camera-wide rules see every frame (even an empty one, so time can pass).
        for rule_id, camera_rule in camera_rules.items():
            effective = config.resolve(rule_id, twin.camera_id, "")
            if not effective.enabled:
                continue
            memory = work.memory.setdefault(rule_id, {})
            for hit in camera_rule.evaluate_camera(frame.objects, effective.params, ctx, memory):
                _record_hit(work, hit, effective, None, frame, twin, closed, touched)
            if not memory:
                del work.memory[rule_id]

    # Episodes quiet for longer than their debounce window are over (a later hit
    # could no longer extend them) — this also handles segments with no detections.
    for key, episode in list(work.episodes.items()):
        effective = config.resolve(episode.rule_id, twin.camera_id, episode.zone_name or "")
        quiet_s = (twin.end_ts - episode.last_ts).total_seconds()
        if not effective.enabled or quiet_s > effective.params.debounce_s:
            _finish(work, key, twin, closed, touched)

    updates = list(closed)
    for key in touched:
        episode = work.episodes.get(key)
        if episode is not None and episode.candidate_id is not None:
            updates.append(_to_update(episode, twin, status="open"))
    updates.sort(key=lambda u: (u.start_ts, u.rule_id, str(u.id)))

    work.last_segment_end = twin.end_ts
    return TwinOutcome(state=work, updates=updates)


def _objects_by_zone(
    objects: Iterable[FrameObject], zones_by_name: dict[str, ZoneInternal]
) -> dict[str, list[FrameObject]]:
    """Group a frame's objects by the (known) zones they stand in. Names with no
    matching zone — e.g. a zone deleted after the twin was written — are ignored."""
    grouped: dict[str, list[FrameObject]] = defaultdict(list)
    for obj in objects:
        for zone_name in obj.zones:
            if zone_name in zones_by_name:
                grouped[zone_name].append(obj)
    return grouped


def _record_hit(
    work: CameraState,
    hit: Hit,
    effective: EffectiveRule,
    zone: ZoneInternal | None,
    frame: Frame,
    twin: TwinV1,
    closed: list[CandidateUpdate],
    touched: set[str],
) -> None:
    ts = frame.ts
    rule = effective.rule
    params = effective.params
    zone_name = zone.name if zone is not None else ""  # camera-wide rules have no zone
    key = f"{rule.id}|{zone_name}|{hit.key}"

    episode = work.episodes.get(key)
    if episode is not None and (ts - episode.last_ts).total_seconds() > params.debounce_s:
        _finish(work, key, twin, closed, touched)  # too long since the last hit: a new episode
        episode = None
    if episode is None:
        episode = Episode(
            rule_id=rule.id,
            event_type=rule.event_type,
            severity=effective.severity,
            zone_id=zone.id if zone is not None else None,
            zone_name=zone.name if zone is not None else None,
            hit_key=hit.key,
            first_ts=min(ts, hit.since) if hit.since is not None else ts,
            last_ts=ts,
            frames=0,
        )
        work.episodes[key] = episode

    episode.last_ts = ts
    episode.frames += 1
    episode.score = max(episode.score, hit.score)
    episode.params = params.model_dump(mode="json")
    for track_id in hit.track_ids:
        if track_id not in episode.track_ids:
            episode.track_ids.append(track_id)
    if twin.segment_id not in episode.segment_ids:
        episode.segment_ids.append(twin.segment_id)
    episode.evidence = add_evidence(
        episode.evidence, frame_evidence(frame, twin.segment_id, hit.track_ids)
    )
    for name, value in hit.metrics.items():
        peak = f"peak_{name}"
        episode.peaks[peak] = max(episode.peaks.get(peak, value), value)

    if (
        episode.candidate_id is None
        and episode.frames >= params.required_frames()
        and episode.duration_s >= params.required_duration_s()
    ):
        episode.candidate_id = str(
            candidate_id(twin.camera_id, rule.id, zone_name, hit.key, episode.first_ts)
        )
    touched.add(key)


def _finish(
    work: CameraState,
    key: str,
    twin: TwinV1,
    closed: list[CandidateUpdate],
    touched: set[str],
) -> None:
    """Close an episode: if it ever became a candidate, emit its final update."""
    episode = work.episodes.pop(key)
    touched.discard(key)
    if episode.candidate_id is not None:
        closed.append(_to_update(episode, twin, status="closed"))


def _to_update(episode: Episode, twin: TwinV1, *, status: CandidateStatus) -> CandidateUpdate:
    assert episode.candidate_id is not None  # noqa: S101 - callers only pass candidates
    return CandidateUpdate(
        id=uuid.UUID(episode.candidate_id),
        site_id=twin.site_id,
        camera_id=twin.camera_id,
        rule_id=episode.rule_id,
        event_type=episode.event_type,
        severity=episode.severity,
        zone_id=episode.zone_id,
        zone_name=episode.zone_name,
        track_ids=list(episode.track_ids),
        segment_ids=list(episode.segment_ids),
        start_ts=episode.first_ts,
        end_ts=episode.last_ts,
        rule_score=episode.score,
        status=status,
        details={
            "frames": episode.frames,
            "duration_s": round(episode.duration_s, 3),
            **episode.peaks,
            "params": episode.params,
            "evidence": [item.model_dump(mode="json") for item in episode.evidence],
        },
    )
