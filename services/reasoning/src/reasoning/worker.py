"""The reasoning worker: claims a job, runs the pipeline, stores the incident (design §8.1).

    context -> footage -> phase timeline (TG) -> evidence per stage × camera (PhaVR)
            -> report (synthesis, citation-checked) -> store -> incidentready.v1

Progress is written to the job row after every step so the UI can show it. Anything that goes
wrong ends the job as `failed` with a reason and leaves the incident row `failed` too (with the
raw model output when synthesis was the problem) — never a half-written `generated` report.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vms_common.contracts.event import Severity
from vms_common.contracts.reasoning import IncidentReadyV1
from vms_common.contracts.ws import (
    IncidentReadyData,
    JobProgressData,
    incident_ready,
    job_progress,
)
from vms_common.ids import uuid7_str
from vms_common.kafka.producer import KafkaProducerClient
from vms_common.llm import Gateway
from vms_common.logging import bind_context, clear_context, get_logger
from vms_common.vqa_bank import VQABank

from reasoning.adapters.footage import Footage, FootFrame
from reasoning.adapters.notify import Notifier
from reasoning.adapters.store import JobRow, ReasoningStore
from reasoning.domain.context import build_context
from reasoning.domain.evidence import PhaseReading, build_bundle
from reasoning.metrics import job_seconds, jobs_total, queue_depth
from reasoning.reports.daily import ReportQueue
from reasoning.reports.daily import generate as generate_report
from reasoning.reports.pdf import write_daily_pdf, write_incident_pdf
from reasoning.settings import ReasoningSettings
from reasoning.steps.phases import locate_phases
from reasoning.steps.readings import read_view
from reasoning.steps.synthesis import synthesize

log = get_logger(__name__)


class JobFailedError(Exception):
    """A job cannot produce a report; the message is shown to the operator."""


class ReasoningWorker:
    _notifier: Notifier | None = None  # optional: no browsers to tell is not an error
    _incident: uuid.UUID | None = None  # the report the current job is writing
    _attached = False  # whether that report's row exists yet
    _fraction = 0.0  # how far the current job got, for the message that says it failed

    def __init__(
        self,
        *,
        settings: ReasoningSettings,
        store: ReasoningStore,
        footage: Footage,
        gateway: Gateway,
        bank: VQABank,
        producer: KafkaProducerClient | None,
        profile: str,
        tz: ZoneInfo,
        reports: ReportQueue | None = None,
        sessions: async_sessionmaker[AsyncSession] | None = None,
        notifier: Notifier | None = None,
    ) -> None:
        self._s = settings
        self._store = store
        self._footage = footage
        self._gateway = gateway
        self._bank = bank
        self._producer = producer
        self._profile = profile
        self._tz = tz
        self._reports = reports
        self._sessions = sessions
        self._notifier = notifier
        self._last_schedule_check = 0.0
        self._stage: tuple[str, float] | None = None

    async def run_forever(self) -> None:
        while True:
            queue_depth.set(await self._store.queued_count())
            job = await self._store.claim(self._s.job_lease_s)
            if job is not None:
                await self.process(job)
                continue
            if await self._daily_report_step():
                continue
            await asyncio.sleep(self._s.poll_s)

    async def _daily_report_step(self) -> bool:
        """Queue yesterday's report when it is time, then work one queued report. True if a
        report was worked (the loop should look for more before sleeping)."""
        if self._reports is None or self._sessions is None:
            return False
        try:
            await self._schedule_daily()
            report_id = await self._reports.claim()
            if report_id is None:
                return False
            try:
                await generate_report(self._sessions, self._gateway, report_id, self._tz)
                await self._daily_pdf(report_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("daily_report_failed", report_id=str(report_id))
                await self._reports.fail(report_id, f"{type(exc).__name__}: {exc}")
            return True
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("daily_report_step_failed")
            return False

    async def _schedule_daily(self) -> None:
        now = time.monotonic()
        if not self._s.daily_report_auto or now - self._last_schedule_check < 60:
            return
        self._last_schedule_check = now
        local = datetime.now(self._tz)
        if local.hour < self._s.daily_report_hour:
            return
        day = local.date() - timedelta(days=1)
        if not await self._reports.scheduled_exists(day):
            await self._reports.enqueue(day, day)
            log.info("daily_report_queued", day=str(day))

    async def process(self, job: JobRow) -> None:
        bind_context(job_id=str(job.id))
        incident_id = uuid.UUID(uuid7_str())
        self._incident, self._attached, self._fraction = incident_id, False, 0.0
        try:
            await self._run(job, incident_id)
        except JobFailedError as exc:
            log.warning("job_failed", reason=str(exc))
            await self._fail(job, incident_id, str(exc))
            jobs_total.labels(outcome="failed").inc()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # the queue must survive any one bad job
            log.exception("job_crashed")
            await self._fail(job, incident_id, f"unexpected error: {type(exc).__name__}: {exc}")
            jobs_total.labels(outcome="crashed").inc()
        else:
            jobs_total.labels(outcome="done").inc()
        finally:
            self._close_stage()
            self._incident, self._attached = None, False
            clear_context()

    async def _step(self, job: JobRow, stage: str, fraction: float) -> None:
        self._close_stage()
        self._stage = (_coarse(stage), time.monotonic())
        await self._store.progress(job.id, stage, fraction, lease_s=self._s.job_lease_s)
        self._fraction = fraction
        await self._push_progress(job, "running", stage, fraction)

    async def _push_progress(self, job: JobRow, status: str, stage: str, fraction: float) -> None:
        """Tell the browsers where the job is (`job.progress`). The incident id is only known once
        the report row exists, so the first steps carry none."""
        if self._notifier is None:
            return
        data = JobProgressData(
            job_id=str(job.id),
            status=status,  # type: ignore[arg-type]
            stage=stage,
            fraction=min(max(fraction, 0.0), 1.0),
            group_id=str(job.group_id) if job.group_id else None,
            incident_id=str(self._incident) if self._incident and self._attached else None,
        )
        await self._notifier.send(job_progress(data))

    def _close_stage(self) -> None:
        """Record how long the stage that just ended took (stages are the coarse names the
        dashboard graphs, not the per-camera progress text)."""
        if self._stage is not None:
            name, started = self._stage
            job_seconds.labels(stage=name).observe(time.monotonic() - started)
            self._stage = None

    async def _run(self, job: JobRow, incident_id: uuid.UUID) -> None:
        s = self._s
        await self._store.abandon_incidents(job.id)
        # --- context ---------------------------------------------------------------
        await self._step(job, "gathering events", 0.03)
        group_id = job.group_id
        event_ids = list(job.event_ids)
        if group_id is not None:
            event_ids = await self._store.group_event_ids(group_id) or event_ids
        events = await self._store.load_events(event_ids)
        ctx = build_context(
            events,
            group_id=str(group_id) if group_id else None,
            pad_before_s=s.pad_before_s,
            pad_after_s=s.pad_after_s,
            max_views=s.max_views,
        )
        if ctx is None:
            raise JobFailedError("none of the events is available (rejected or removed)")
        await self._store.create_incident(
            incident_id=incident_id,
            job_id=job.id,
            group_id=group_id,
            event_ids=[e.id for e in ctx.events],
            severity=ctx.severity,
            event_type=ctx.event_type,
            title=f"Analysing {ctx.event_type.replace('_', ' ')} on {ctx.primary.camera_id}…",
            camera_ids=ctx.all_cameras,
            window_start=ctx.window.start,
            window_end=ctx.window.end,
        )
        await self._attach(job, incident_id)

        # --- footage ---------------------------------------------------------------
        await self._step(job, "collecting footage", 0.08)
        footage: dict[str, list[FootFrame]] = {}
        for cam in ctx.cameras:
            footage[cam] = await self._footage.frames(cam, ctx.window.start, ctx.window.end)
        if len(footage.get(ctx.primary.camera_id, [])) < 2:
            raise JobFailedError(
                "the recording for this incident is no longer available (retention) "
                "or was not analysed"
            )
        cameras = [c for c in ctx.cameras if footage.get(c)]

        # --- phases ----------------------------------------------------------------
        await self._step(job, "locating the phases", 0.15)
        timeline, fallback, tg_source = await locate_phases(
            self._gateway,
            self._footage,
            ctx,
            footage[ctx.primary.camera_id],
            n_frames=s.phase_frames,
        )

        # --- evidence --------------------------------------------------------------
        questions = list(self._bank.questions_for(ctx.event_type))[: s.questions_per_view]
        jobs = [(span, cam) for span in timeline for cam in cameras]
        readings: dict[str, list] = {}
        for i, (span, cam) in enumerate(jobs):
            await self._step(
                job, f"reading {span.phase} · {cam}", 0.2 + 0.55 * i / max(len(jobs), 1)
            )
            view = await read_view(
                self._gateway,
                self._footage,
                ctx,
                span,
                cam,
                footage[cam],
                questions,
                n_frames=s.frames_per_view,
            )
            if view is not None:
                readings.setdefault(span.phase, []).append(view)
        phase_readings = [
            PhaseReading(phase=sp.phase, views=readings[sp.phase])
            for sp in timeline
            if sp.phase in readings
        ]
        if not phase_readings:
            raise JobFailedError("the vision model could not describe any stage of this incident")

        bundle = build_bundle(
            group_id=ctx.group_id,
            event_type=ctx.event_type,
            severity=ctx.severity,  # type: ignore[arg-type]
            cameras=cameras,
            primary_camera=ctx.primary.camera_id,
            window=ctx.window,
            timeline=timeline,
            readings=phase_readings,
            events=[(e.id, e.camera_id, e.event_type, e.caption) for e in ctx.events],
            provenance={
                "tg": tg_source,
                "phavr": f"zero-shot:{self._profile}",
                "fallback_used": fallback,
                "profile": self._profile,
            },
        )
        # Keep the frames the report cites past the keyframe bucket's retention.
        for ph in bundle.phases:
            for v in ph.views:
                for fr in v.frames:
                    dest = f"s3://{s.evidence_bucket}/{incident_id}/{fr.id}.jpg"
                    await self._footage.keep(fr.uri, dest)
                    fr.uri = dest

        # --- report ----------------------------------------------------------------
        await self._step(job, "writing the report", 0.8)
        when = (
            f"{ctx.window.start.astimezone(self._tz):%d %b %Y %H:%M:%S}"
            f" to {ctx.window.end.astimezone(self._tz):%H:%M:%S} ({self._tz})"
        )
        result = await synthesize(
            self._gateway,
            ctx,
            bundle,
            incident_id=str(incident_id),
            tz=self._tz,
            retries=s.synthesis_retries,
            profile=self._profile,
            when=when,
        )
        provenance = {
            "tg": tg_source,
            "fallback_used": fallback,
            "profile": self._profile,
            "synthesis_model": result.model,
            "model_calls": result.calls,
        }
        if result.report is None:
            await self._store.complete_incident(
                incident_id,
                status="failed",
                title=None,
                report=None,
                evidence=bundle.model_dump(mode="json"),
                provenance=provenance,
                raw_output=result.raw[:20000],
            )
            await self._announce(
                incident_id, ctx.group_id, "failed", ctx.severity, "Analysis failed"
            )
            raise JobFailedError(result.error or "the report could not be written")

        report = result.report
        final_provenance = {**provenance, **report.provenance}
        copy = await self._keep_report(
            incident_id,
            {
                "incident_id": str(incident_id),
                "report": report.model_dump(mode="json"),
                "evidence": bundle.model_dump(mode="json"),
                "provenance": final_provenance,
            },
        )
        if copy:
            final_provenance["report_uri"] = copy
        await self._store.complete_incident(
            incident_id,
            status="generated",
            title=report.title,
            report=report.model_dump(mode="json"),
            evidence=bundle.model_dump(mode="json"),
            provenance=final_provenance,
            raw_output=None,
        )
        await self._finish_generated(
            job, incident_id, ctx.group_id, ctx.severity, report.title, result.calls
        )
        await self._incident_pdf(incident_id)

    async def _attach(self, job: JobRow, incident_id: uuid.UUID) -> None:
        """The report row exists: link it to the job, and from now on say so in the progress."""
        await self._store.attach_incident(job.id, incident_id)
        self._attached = True

    async def _finish_generated(
        self,
        job: JobRow,
        incident_id: uuid.UUID,
        group_id: str | None,
        severity: Severity,
        title: str,
        calls: int,
    ) -> None:
        """The report is stored: close the job, announce it (Kafka, browsers), say it is done."""
        await self._store.finish(job.id)
        await self._announce(incident_id, group_id, "generated", severity, title)
        log.info("incident_generated", incident_id=str(incident_id), calls=calls)
        await self._push_progress(job, "done", "the report is ready", 1.0)

    async def _keep_report(self, incident_id: uuid.UUID, payload: dict) -> str | None:
        """A copy of the finished report in object storage, beside its PDF: the database row stays
        the source of truth, this one outlives a lost database and can be handed over as it is.
        Its failure leaves the report without a copy, nothing more."""
        uri = f"s3://{self._s.reports_bucket}/incidents/{incident_id}/report.json"
        try:
            data = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
            await self._footage.put(uri, data, "application/json")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("incident_copy_failed", incident_id=str(incident_id))
            return None
        return uri

    async def _incident_pdf(self, incident_id: uuid.UUID) -> None:
        """The PDF of a finished report. Its failure leaves a report without a PDF, nothing more."""
        if not self._s.pdf_enabled or self._sessions is None:
            return
        try:
            uri = await write_incident_pdf(
                sessions=self._sessions,
                images=self._footage,
                store=self._footage,
                incident_id=incident_id,
                bucket=self._s.reports_bucket,
                tz=self._tz,
                site=self._s.site_name,
            )
            log.info("incident_pdf_written", incident_id=str(incident_id), uri=uri)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("incident_pdf_failed", incident_id=str(incident_id))

    async def _daily_pdf(self, report_id: uuid.UUID) -> None:
        if not self._s.pdf_enabled or self._sessions is None:
            return
        try:
            await write_daily_pdf(
                sessions=self._sessions,
                store=self._footage,
                report_id=report_id,
                bucket=self._s.reports_bucket,
                tz=self._tz,
                site=self._s.site_name,
                profile=self._profile,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("daily_pdf_failed", report_id=str(report_id))

    async def _fail(self, job: JobRow, incident_id: uuid.UUID, reason: str) -> None:
        try:
            await self._store.finish(job.id, failed=reason[:500])
        except Exception:
            log.exception("could_not_mark_job_failed")
        try:  # the report row created before the failure must not stay "generating" for ever
            await self._store.abandon_incidents(job.id, reason[:500])
        except Exception:
            log.exception("could_not_mark_incident_failed")
        await self._push_progress(job, "failed", reason[:200], self._fraction)

    async def _announce(
        self,
        incident_id: uuid.UUID,
        group_id: str | None,
        status: str,
        severity: Severity,
        title: str,
    ) -> None:
        if self._notifier is not None:
            await self._notifier.send(
                incident_ready(
                    IncidentReadyData(
                        incident_id=str(incident_id),
                        group_id=group_id,
                        status=status,  # type: ignore[arg-type]
                        severity=severity,
                        title=title,
                    )
                )
            )
        if self._producer is None:
            return
        try:
            await self._producer.send(
                self._s.incidents_topic,
                key=str(incident_id),
                message=IncidentReadyV1(
                    incident_id=str(incident_id),
                    group_id=group_id,
                    status=status,  # type: ignore[arg-type]
                    severity=severity,
                    title=title,
                ),
            )
        except Exception:  # the report is stored; the notice is best-effort
            log.exception("incidentready_not_sent")


def _utcnow() -> datetime:
    return datetime.now(UTC)


_STAGES = (
    ("gathering", "context"),
    ("collecting", "footage"),
    ("locating", "phases"),
    ("reading", "evidence"),
    ("writing", "synthesis"),
)


def _coarse(stage: str) -> str:
    """ "reading action · cam01" -> "evidence": the stage a progress message belongs to."""
    return next((name for word, name in _STAGES if stage.startswith(word)), "other")
