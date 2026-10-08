"""Integration tests: the links to stored PDF reports (P6-J1, P6-J2) against real Postgres and an
S3 test double. Run via `make test-int`."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from vms_common.storage.s3 import S3Client
from vms_db.models import DailyReport, Incident

pytestmark = pytest.mark.integration

PDF = b"%PDF-1.7\n% a stored report\n"


def _incident(pdf_uri: str | None) -> Incident:
    now = datetime.now(UTC)
    return Incident(
        id=uuid.uuid4(),
        status="generated",
        severity="high",
        event_type="intrusion",
        title="Intrusion in the yard",
        camera_ids=["cam01"],
        event_ids=[],
        window_start=now - timedelta(minutes=2),
        window_end=now,
        report={"summary": "A person climbed the fence.", "confidence": 0.8},
        pdf_uri=pdf_uri,
    )


async def _store(s3: S3Client, key: str) -> str:
    await s3.ensure_bucket("vms-reports")
    uri = f"s3://vms-reports/{key}"
    await s3.put_bytes(uri, PDF, content_type="application/pdf")
    return uri


async def test_an_incident_with_a_pdf_links_to_it_and_one_without_says_so(
    client: TestClient,
    admin_access_token: str,
    auth_headers: Callable[[str], dict[str, str]],
    db_session_factory: async_sessionmaker,
    s3_client: S3Client,
) -> None:
    headers = auth_headers(admin_access_token)
    with_pdf = _incident(await _store(s3_client, f"incidents/{uuid.uuid4()}.pdf"))
    without = _incident(None)
    async with db_session_factory() as session:
        session.add_all([with_pdf, without])
        await session.commit()

    listed = {
        i["id"]: i
        for i in client.get("/api/v1/incidents?limit=100", headers=headers).json()["items"]
    }
    assert listed[str(with_pdf.id)]["has_pdf"] is True
    assert listed[str(without.id)]["has_pdf"] is False

    link = client.get(f"/api/v1/incidents/{with_pdf.id}/pdf", headers=headers)
    assert link.status_code == 200, link.text
    body = link.json()
    assert body["expires_in"] == 900 and "X-Amz-Signature" in body["url"]
    assert (
        await asyncio.to_thread(httpx.get, body["url"])
    ).content == PDF  # the link really delivers the stored file

    missing = client.get(f"/api/v1/incidents/{without.id}/pdf", headers=headers)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "NOT_FOUND"
    assert client.get(f"/api/v1/incidents/{uuid.uuid4()}/pdf", headers=headers).status_code == 404
    assert client.get("/api/v1/incidents/not-a-uuid/pdf", headers=headers).status_code == 400


async def test_a_daily_report_with_a_pdf_links_to_it(
    client: TestClient,
    admin_access_token: str,
    auth_headers: Callable[[str], dict[str, str]],
    db_session_factory: async_sessionmaker,
    s3_client: S3Client,
) -> None:
    headers = auth_headers(admin_access_token)
    uri = await _store(s3_client, f"daily/{uuid.uuid4()}.pdf")
    day = date(2026, 10, 6)
    done = DailyReport(id=uuid.uuid4(), date_from=day, date_to=day, status="ready", pdf_uri=uri)
    plain = DailyReport(id=uuid.uuid4(), date_from=day, date_to=day, status="ready")
    async with db_session_factory() as session:
        session.add_all([done, plain])
        await session.commit()

    assert client.get(f"/api/v1/reports/daily/{done.id}", headers=headers).json()["has_pdf"] is True
    link = client.get(f"/api/v1/reports/daily/{done.id}/pdf", headers=headers)
    assert link.status_code == 200, link.text
    assert (await asyncio.to_thread(httpx.get, link.json()["url"])).content == PDF
    assert client.get(f"/api/v1/reports/daily/{plain.id}/pdf", headers=headers).status_code == 404
    assert client.get("/api/v1/reports/daily/not-a-uuid/pdf", headers=headers).status_code == 400
    assert client.get(f"/api/v1/reports/daily/{done.id}/pdf").status_code == 401
