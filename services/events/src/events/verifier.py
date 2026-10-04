"""The VLM verification gate: closed candidates in, verified events out (P3-D4).

Beside the twin consumer, one loop takes candidates the rule engine has finished with (or that
have been going long enough that waiting for them to end would delay the alert) and judges each:

    claim -> pick <= 4 evidence frames -> fetch keyframes -> draw the flagged boxes -> ask the
    model (`event_verify`) -> decide -> write `events.events` -> publish `event.v1`

Everything that can fail has a defined outcome (see `events.domain.verification`):

* a rule with `verify: false` is published as `skipped` without asking anyone;
* a model that cannot be reached (or keyframes that cannot be read) leaves an alert-worthy
  candidate waiting, retried with back-off, and publishes a low-severity one as `skipped`;
* a model that answers with something unreadable counts as `unsure`;
* anything unexpected is logged, counted and retried with back-off, never dropped.

Writes are in the order that survives a crash: the decision row first, the Kafka send second, the
`published_at` tick last. A crash in between re-sends the event (consumers ignore a duplicate)
rather than losing it; a crash during the model call lets the lease expire and the candidate be
judged again (the gateway's response cache makes that cheap).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Protocol

from vms_common.contracts.event import EventV1, Verification
from vms_common.llm import (
    Gateway,
    ImageInput,
    LLMOutputError,
    LLMUnavailableError,
    render_prompt,
)
from vms_common.logging import bind_context, clear_context, get_logger

from events.domain.config import RulesConfig
from events.domain.evidence import EvidenceFrame
from events.domain.overlay import draw_boxes
from events.domain.records import EventRow, PendingCandidate
from events.domain.rules import registered_rules
from events.domain.verification import (
    PROMPT_VERSION,
    TASK,
    GatePolicy,
    GateStatus,
    Verdict,
    decide,
    offsets_s,
    retry_delay_s,
    select_frames,
    unavailable_action,
    verification_record,
)
from events.metrics import (
    published_total,
    verification_errors_total,
    verification_seconds,
    verifications_total,
)

log = get_logger(__name__)


class EventStore(Protocol):
    async def claim(
        self, *, now: datetime, limit: int, lease_s: float, open_after_s: float, max_age_s: float
    ) -> list[PendingCandidate]: ...

    async def save_event(self, row: EventRow) -> bool: ...

    async def reschedule(self, candidate_id: uuid.UUID, not_before: datetime) -> None: ...

    async def unpublished(self, *, limit: int) -> list[EventRow]: ...

    async def mark_published(self, event_id: uuid.UUID, at: datetime) -> None: ...


class EventPublisher(Protocol):
    async def publish(self, event: EventV1) -> None: ...


class KeyframeSource(Protocol):
    async def load(self, frames: Sequence[EvidenceFrame]) -> list[tuple[EvidenceFrame, bytes]]: ...


@dataclass(frozen=True)
class VerifierOptions:
    batch_size: int = 4
    poll_s: float = 2.0
    lease_s: float = 300.0  # longer than one candidate can take (lease wait + model calls)
    open_after_s: float = (
        90.0  # judge a candidate still going once it has been a candidate this long
    )
    max_age_s: float = 6 * 3600.0  # never judge a candidate that ended longer ago than this
    retry_base_s: float = 5.0
    retry_cap_s: float = 300.0
    publish_batch: int = 50


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Verifier:
    def __init__(
        self,
        *,
        gateway: Gateway,
        store: EventStore,
        publisher: EventPublisher,
        keyframes: KeyframeSource,
        rules: RulesConfig,
        policy: GatePolicy | None = None,
        options: VerifierOptions | None = None,
        clock: Callable[[], datetime] = _utcnow,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._gateway = gateway
        self._store = store
        self._publisher = publisher
        self._keyframes = keyframes
        self._rules = rules
        self._policy = policy or GatePolicy()
        self._options = options or VerifierOptions()
        self._clock = clock
        self._sleep = sleep

    # --- the loop ----------------------------------------------------------------------

    async def run(self) -> None:
        """Judge candidates until cancelled. A failed pass (database or Kafka down) is logged and
        the loop carries on after a pause: the work is still in the database."""
        while True:
            try:
                worked = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("verifier_pass_failed")
                worked = 0
            if not worked:
                await self._sleep(self._options.poll_s)

    async def run_once(self) -> int:
        """One pass: send what is waiting to be sent, then judge up to a batch. Returns how many
        candidates were claimed (0 means idle)."""
        await self.publish_pending()
        opts = self._options
        claimed = await self._store.claim(
            now=self._clock(),
            limit=opts.batch_size,
            lease_s=opts.lease_s,
            open_after_s=opts.open_after_s,
            max_age_s=opts.max_age_s,
        )
        for candidate in claimed:
            await self._guarded(candidate)
        return len(claimed)

    async def publish_pending(self) -> int:
        """Send decisions that were saved but never announced (a crash, Kafka down). Stops at the
        first failure: if Kafka is down the rest would fail too."""
        sent = 0
        for row in await self._store.unpublished(limit=self._options.publish_batch):
            try:
                await self._publisher.publish(_event_v1(row))
            except Exception:
                log.exception("event_publish_failed", event_id=str(row.id))
                break
            await self._store.mark_published(row.id, self._clock())
            published_total.labels(status=row.status).inc()
            sent += 1
        return sent

    # --- one candidate -----------------------------------------------------------------

    async def _guarded(self, candidate: PendingCandidate) -> None:
        bind_context(candidate_id=str(candidate.id), camera_id=candidate.camera_id)
        try:
            await self._judge(candidate)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Unexpected (not "the model is down", which `_judge` handles): keep it, say so, and
            # try again later rather than letting one candidate stop the others.
            log.exception("verification_failed", rule_id=candidate.rule_id)
            verification_errors_total.labels(rule=candidate.rule_id).inc()
            delay = retry_delay_s(
                candidate.attempts,
                base_s=self._options.retry_base_s,
                cap_s=self._options.retry_cap_s,
            )
            await self._store.reschedule(candidate.id, self._clock() + timedelta(seconds=delay))
        finally:
            clear_context()

    async def _judge(self, candidate: PendingCandidate) -> None:
        if not self._verify_enabled(candidate):
            await self._decide(
                candidate, "skipped", "verification is turned off for this rule", frames=[]
            )
            return
        chosen = select_frames(candidate.evidence)
        if not chosen:
            await self._decide(
                candidate, "skipped", "the candidate recorded no keyframes", frames=[]
            )
            return

        images, shown = await self._pictures(chosen)
        if not images:
            await self._unavailable(candidate, "its keyframes could not be read", chosen)
            return

        prompt = render_prompt(
            TASK,
            PROMPT_VERSION,
            claim=_claim(candidate),
            camera=candidate.camera_id,
            zone=candidate.zone_name,
            n_frames=len(shown),
            offsets=offsets_s(shown),
        )
        started = perf_counter()
        try:
            result = await self._gateway.vision(TASK, prompt, images, response_model=Verdict)
        except LLMUnavailableError as exc:
            await self._unavailable(candidate, f"the model could not be reached ({exc})", shown)
            return
        except LLMOutputError:
            verdict = Verdict(verdict="unsure", confidence=0.0, caption="")
            decision = decide(verdict, candidate.severity, self._policy)
            await self._decide(
                candidate,
                decision.status,
                f"the model's answer could not be read, counted as unsure; {decision.reason}",
                verdict=verdict,
                flagged=decision.flagged,
                latency_ms=round((perf_counter() - started) * 1000),
                frames=shown,
            )
            return

        verdict = result.parsed
        assert isinstance(verdict, Verdict)  # noqa: S101 - the gateway validated `response_model`
        decision = decide(verdict, candidate.severity, self._policy)
        await self._decide(
            candidate,
            decision.status,
            decision.reason,
            verdict=verdict,
            flagged=decision.flagged,
            model=f"{result.provider}/{result.model}",
            latency_ms=round(result.latency_s * 1000),
            frames=shown,
        )

    async def _pictures(
        self, chosen: list[EvidenceFrame]
    ) -> tuple[list[ImageInput], list[EvidenceFrame]]:
        """The frames' images with their boxes drawn, and the frames that made it (a keyframe
        that cannot be fetched or decoded is left out, not fatal)."""
        images: list[ImageInput] = []
        shown: list[EvidenceFrame] = []
        for frame, data in await self._keyframes.load(chosen):
            try:
                images.append(ImageInput(data=draw_boxes(data, frame.boxes)))
            except OSError as exc:  # PIL.UnidentifiedImageError and friends
                log.warning("keyframe_not_an_image", uri=frame.keyframe_uri, error=str(exc))
                continue
            shown.append(frame)
        return images, shown

    def _verify_enabled(self, candidate: PendingCandidate) -> bool:
        try:
            return self._rules.resolve(
                candidate.rule_id, candidate.camera_id, candidate.zone_name or ""
            ).verify
        except ValueError:
            return True  # a rule that is no longer registered: when in doubt, ask the model

    async def _unavailable(
        self, candidate: PendingCandidate, why: str, frames: list[EvidenceFrame]
    ) -> None:
        now = self._clock()
        waited = (now - candidate.first_at).total_seconds()
        if unavailable_action(candidate.severity, waited, self._policy) == "hold":
            delay = retry_delay_s(
                candidate.attempts,
                base_s=self._options.retry_base_s,
                cap_s=self._options.retry_cap_s,
            )
            await self._store.reschedule(candidate.id, now + timedelta(seconds=delay))
            verifications_total.labels(rule=candidate.rule_id, outcome="held").inc()
            log.warning(
                "candidate_held",
                why=why,
                severity=candidate.severity,
                attempts=candidate.attempts,
                waited_s=round(waited),
                retry_in_s=delay,
            )
            return
        note = (
            f"published unverified after waiting {waited:.0f} s"
            if waited > 0
            else "published unverified"
        )
        await self._decide(
            candidate,
            "skipped",
            f"{why}; {note} ({candidate.severity} severity)",
            frames=frames,
        )

    async def _decide(
        self,
        candidate: PendingCandidate,
        status: GateStatus,
        reason: str,
        *,
        verdict: Verdict | None = None,
        flagged: bool = False,
        model: str | None = None,
        latency_ms: int | None = None,
        frames: Sequence[EvidenceFrame],
    ) -> None:
        row = EventRow(
            id=candidate.id,
            site_id=candidate.site_id,
            camera_id=candidate.camera_id,
            event_type=candidate.event_type,
            severity=candidate.severity,
            rule_id=candidate.rule_id,
            rule_score=candidate.rule_score,
            zone_id=candidate.zone_id,
            zone_name=candidate.zone_name,
            track_ids=list(candidate.track_ids),
            segment_ids=list(candidate.segment_ids),
            keyframe_uris=[frame.keyframe_uri for frame in frames],
            start_ts=candidate.start_ts,
            end_ts=candidate.end_ts,
            status=status,
            verification=verification_record(
                status,
                reason,
                verdict=verdict,
                flagged=flagged,
                model=model,
                latency_ms=latency_ms,
                frames=len(frames),
                attempts=candidate.attempts,
                prompt_version=PROMPT_VERSION if model or verdict else None,
            ),
        )
        if not await self._store.save_event(row):
            log.info("candidate_already_decided")  # another worker got there first
            return
        verifications_total.labels(rule=candidate.rule_id, outcome=status).inc()
        if latency_ms is not None:
            verification_seconds.observe(latency_ms / 1000)
        log.info(
            "candidate_decided",
            status=status,
            reason=reason,
            rule_id=candidate.rule_id,
            severity=candidate.severity,
            verdict=verdict.verdict if verdict else None,
            confidence=verdict.confidence if verdict else None,
            latency_ms=latency_ms,
        )
        if status != "rejected":
            await self._announce(row)

    async def _announce(self, row: EventRow) -> None:
        """Send it now; if that fails the row stays unpublished and the next pass sends it."""
        try:
            await self._publisher.publish(_event_v1(row))
        except Exception:
            log.exception("event_publish_failed", event_id=str(row.id))
            return
        await self._store.mark_published(row.id, self._clock())
        published_total.labels(status=row.status).inc()


def _claim(candidate: PendingCandidate) -> str:
    try:
        return registered_rules()[candidate.rule_id].description
    except KeyError:
        return f'An event of type "{candidate.event_type.replace("_", " ")}" is happening.'


def _event_v1(row: EventRow) -> EventV1:
    record = row.verification
    return EventV1(
        event_id=str(row.id),
        site_id=row.site_id,
        camera_id=row.camera_id,
        event_type=row.event_type,
        severity=row.severity,  # type: ignore[arg-type]
        start_ts=row.start_ts,
        end_ts=row.end_ts,
        rule_id=row.rule_id,
        rule_score=row.rule_score,
        zone_id=row.zone_id,
        track_ids=row.track_ids,
        segment_ids=row.segment_ids,
        keyframe_uris=row.keyframe_uris,
        verification=Verification(
            status=row.status,  # type: ignore[arg-type]
            confidence=record.get("confidence"),
            caption=record.get("caption"),
            model=record.get("model"),
            latency_ms=record.get("latency_ms"),
        ),
    )
