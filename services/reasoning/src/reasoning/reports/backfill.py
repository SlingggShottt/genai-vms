"""Write the PDF of every finished report that has none (reports made before PDFs existed, or
whose PDF failed): `python -m reasoning.reports.backfill`. Safe to run again; prints what it did."""

from __future__ import annotations

import asyncio
from zoneinfo import ZoneInfo

from sqlalchemy import text
from vms_common.config import LLMSettings
from vms_common.logging import configure_logging, get_logger
from vms_common.storage.s3 import S3Client
from vms_db.session import create_engine, create_session_factory

from reasoning.adapters.footage import Footage
from reasoning.adapters.store import ReasoningStore
from reasoning.reports.pdf import write_daily_pdf, write_incident_pdf
from reasoning.settings import ReasoningSettings

log = get_logger(__name__)


async def _amain() -> None:
    settings = ReasoningSettings()
    configure_logging(level=settings.log_level)
    engine = create_engine(settings.db)
    sessions = create_session_factory(engine)
    s3 = S3Client(
        endpoint_url=settings.storage.endpoint_url,
        access_key=settings.storage.access_key,
        secret_key=settings.storage.secret_key,
        region=settings.storage.region,
    )
    await s3.ensure_bucket(settings.reports_bucket)
    footage = Footage(ReasoningStore(sessions), s3)
    tz = ZoneInfo(settings.site_timezone)
    profile = LLMSettings().profile
    done = {"incidents": 0, "daily": 0, "failed": 0}
    async with sessions() as s:
        incidents = (
            (
                await s.execute(
                    text(
                        "SELECT id FROM reasoning.incidents WHERE report IS NOT NULL "
                        "AND pdf_uri IS NULL ORDER BY created_at"
                    )
                )
            )
            .scalars()
            .all()
        )
        reports = (
            (
                await s.execute(
                    text(
                        "SELECT id FROM reasoning.daily_reports WHERE status = 'ready' "
                        "AND pdf_uri IS NULL ORDER BY created_at"
                    )
                )
            )
            .scalars()
            .all()
        )
    for incident_id in incidents:
        try:
            await write_incident_pdf(
                sessions=sessions,
                images=footage,
                store=footage,
                incident_id=incident_id,
                bucket=settings.reports_bucket,
                tz=tz,
                site=settings.site_name,
            )
            done["incidents"] += 1
        except Exception:
            log.exception("backfill_incident_failed", incident_id=str(incident_id))
            done["failed"] += 1
    for report_id in reports:
        try:
            await write_daily_pdf(
                sessions=sessions,
                store=footage,
                report_id=report_id,
                bucket=settings.reports_bucket,
                tz=tz,
                site=settings.site_name,
                profile=profile,
            )
            done["daily"] += 1
        except Exception:
            log.exception("backfill_daily_failed", report_id=str(report_id))
            done["failed"] += 1
    await engine.dispose()
    print(done)


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
