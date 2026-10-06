"""A job that fails must not leave its half-written report "generating" for ever.

Found on 2026-10-06: an analysis of an event whose footage had expired crashed with NoSuchKey; the
job was marked failed, but the incident row created a moment earlier stayed `generating`, which the
incident list shows as a report still being written."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from reasoning.worker import JobFailedError, ReasoningWorker


class _Store:
    def __init__(self, *, finish_raises: bool = False, abandon_raises: bool = False) -> None:
        self.calls: list[tuple] = []
        self._finish_raises = finish_raises
        self._abandon_raises = abandon_raises

    async def finish(self, job_id, *, failed=None):
        self.calls.append(("finish", job_id, failed))
        if self._finish_raises:
            raise RuntimeError("db down")

    async def abandon_incidents(self, job_id, reason=None):
        self.calls.append(("abandon", job_id, reason))
        if self._abandon_raises:
            raise RuntimeError("db down")


def worker(store: _Store, run) -> ReasoningWorker:
    w = ReasoningWorker.__new__(ReasoningWorker)  # no queue, no gateway: only the failure path
    w._store = store
    w._run = run
    w._stage = None
    return w


def job() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


async def test_a_crash_marks_the_job_and_its_incident_failed_with_the_reason() -> None:
    async def run(job, incident_id):
        raise KeyError("the footage is gone")

    store, j = _Store(), job()
    await worker(store, run).process(j)
    assert [c[0] for c in store.calls] == ["finish", "abandon"]
    assert store.calls[0][2].startswith("unexpected error: KeyError")
    assert store.calls[1] == ("abandon", j.id, store.calls[0][2])  # the same reason on both


async def test_an_ordinary_failure_does_the_same() -> None:
    async def run(job, incident_id):
        raise JobFailedError("none of the events is available")

    store, j = _Store(), job()
    await worker(store, run).process(j)
    assert store.calls == [
        ("finish", j.id, "none of the events is available"),
        ("abandon", j.id, "none of the events is available"),
    ]


async def test_a_success_touches_neither() -> None:
    async def run(job, incident_id):
        return None

    store = _Store()
    await worker(store, run).process(job())
    assert store.calls == []


async def test_a_failure_to_record_the_failure_does_not_stop_the_queue_or_the_other_update() -> (
    None
):
    async def run(job, incident_id):
        raise RuntimeError("boom")

    for store in (_Store(finish_raises=True), _Store(abandon_raises=True)):
        await worker(store, run).process(job())  # must not raise
        assert [c[0] for c in store.calls] == ["finish", "abandon"]  # each was still tried
