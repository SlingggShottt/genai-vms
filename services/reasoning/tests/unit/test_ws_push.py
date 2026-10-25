"""What the worker tells the browsers (`job.progress`, `incident.ready`) and the copy of the report
it keeps in object storage. No Redis, no model: the notifier and the store are fakes."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from reasoning.adapters.notify import RedisNotifier
from reasoning.worker import JobFailedError, ReasoningWorker
from redis.exceptions import ConnectionError as RedisConnectionError
from vms_common.contracts.ws import IncidentReadyData, JobProgressData, WsMessage


class Notes:
    """A notifier that remembers what it was asked to send."""

    def __init__(self, ok: bool = True) -> None:
        self.sent: list[WsMessage] = []
        self.ok = ok

    async def send(self, message: WsMessage) -> bool:
        self.sent.append(message)
        return self.ok


class Store:
    def __init__(self) -> None:
        self.progress_calls: list[tuple] = []

    async def progress(self, job_id, stage, fraction, *, lease_s):
        self.progress_calls.append((stage, fraction))

    async def finish(self, job_id, *, failed=None):
        return None

    async def abandon_incidents(self, job_id, reason=None):
        return None


def worker(notifier=None, store=None, run=None) -> ReasoningWorker:
    w = ReasoningWorker.__new__(ReasoningWorker)
    w._store = store or Store()
    w._notifier = notifier
    w._s = SimpleNamespace(job_lease_s=60, reports_bucket="vms-reports")
    w._stage = None
    w._producer = None
    if run:
        w._run = run
    return w


def job(group: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), group_id=uuid.uuid4() if group else None)


def data(message: WsMessage) -> JobProgressData:
    assert message.type == "job.progress"
    return JobProgressData.model_validate(message.data)


# ---- progress -----------------------------------------------------------------------------------


async def test_each_step_is_pushed_with_its_words_and_its_fraction() -> None:
    notes, j = Notes(), job()
    w = worker(notes)
    await w._step(j, "collecting footage", 0.08)
    await w._step(j, "reading action · cam02", 0.45)
    steps = [data(m) for m in notes.sent]
    assert [(s.stage, s.fraction, s.status) for s in steps] == [
        ("collecting footage", 0.08, "running"),
        ("reading action · cam02", 0.45, "running"),
    ]
    assert steps[0].job_id == str(j.id) and steps[0].group_id == str(j.group_id)


async def test_the_database_is_told_before_the_browsers() -> None:
    order: list[str] = []
    notes, store = Notes(), Store()
    notes_send = notes.send

    async def send(message):
        order.append("push")
        return await notes_send(message)

    async def progress(job_id, stage, fraction, *, lease_s):
        order.append("db")

    notes.send, store.progress = send, progress
    await worker(notes, store)._step(job(), "x", 0.5)
    assert order == ["db", "push"]  # a client that refetches on the push finds the new state


async def test_the_incident_id_is_sent_only_once_the_report_row_exists() -> None:
    notes, j, w = Notes(), job(), None
    w = worker(notes)
    incident = uuid.uuid4()
    w._incident, w._attached = incident, False
    await w._step(j, "gathering events", 0.03)
    w._attached = True
    await w._step(j, "collecting footage", 0.08)
    first, second = (data(m) for m in notes.sent)
    assert first.incident_id is None and second.incident_id == str(incident)


async def test_a_job_with_no_group_sends_none_and_a_fraction_is_kept_in_range() -> None:
    notes = Notes()
    w = worker(notes)
    await w._step(job(group=False), "writing the report", 1.7)
    assert data(notes.sent[0]).group_id is None and data(notes.sent[0]).fraction == 1.0


async def test_without_a_notifier_a_step_still_records_progress() -> None:
    store = Store()
    await worker(None, store)._step(job(), "x", 0.2)
    assert store.progress_calls == [("x", 0.2)]


async def test_a_notifier_that_cannot_publish_does_not_fail_the_step() -> None:
    store = Store()
    await worker(Notes(ok=False), store)._step(job(), "x", 0.2)
    assert store.progress_calls == [("x", 0.2)]


# ---- how a job ends -----------------------------------------------------------------------------


async def test_a_failed_job_says_failed_with_how_far_it_got_and_why() -> None:
    notes = Notes()

    async def run(j, incident_id):
        await w._step(j, "locating the phases", 0.15)
        raise JobFailedError("the recording is no longer available")

    w = worker(notes, run=run)
    await w.process(job())
    last = data(notes.sent[-1])
    assert (last.status, last.fraction) == ("failed", 0.15)
    assert last.stage == "the recording is no longer available"


async def test_a_crash_is_pushed_as_failed_too() -> None:
    notes = Notes()

    async def run(j, incident_id):
        raise KeyError("boom")

    await worker(notes, run=run).process(job())
    assert data(notes.sent[-1]).status == "failed"
    assert data(notes.sent[-1]).stage.startswith("unexpected error: KeyError")


async def test_a_job_that_succeeds_pushes_nothing_by_itself() -> None:
    notes = Notes()

    async def run(j, incident_id):
        return None

    await worker(notes, run=run).process(job())
    assert notes.sent == []  # `done` is pushed by the step that finishes the report


async def test_the_next_job_does_not_inherit_the_last_ones_report() -> None:
    notes = Notes()
    w = worker(notes)

    async def run(j, incident_id):
        w._attached = True
        await w._step(j, "a", 0.1)

    w._run = run
    await w.process(job())
    first_incident = data(notes.sent[-1]).incident_id

    async def run2(j, incident_id):
        await w._step(j, "b", 0.1)

    w._run = run2
    await w.process(job())
    assert first_incident is not None and data(notes.sent[-1]).incident_id is None


# ---- the report is ready ------------------------------------------------------------------------


async def test_a_finished_report_is_announced_to_the_browsers_without_kafka() -> None:
    notes = Notes()
    w = worker(notes)  # no producer at all
    incident, group = uuid.uuid4(), str(uuid.uuid4())
    await w._announce(incident, group, "generated", "high", "Person climbs the fence")
    (message,) = notes.sent
    ready = IncidentReadyData.model_validate(message.data)
    assert message.type == "incident.ready"
    assert (ready.incident_id, ready.group_id, ready.status) == (str(incident), group, "generated")
    assert (ready.severity, ready.title) == ("high", "Person climbs the fence")


async def test_a_failed_report_is_announced_as_failed() -> None:
    notes = Notes()
    await worker(notes)._announce(uuid.uuid4(), None, "failed", "low", "Analysis failed")
    assert IncidentReadyData.model_validate(notes.sent[0].data).status == "failed"


# ---- the copy in object storage -----------------------------------------------------------------


class Objects:
    def __init__(self, fail: bool = False) -> None:
        self.put_calls: list[tuple[str, bytes, str]] = []
        self.fail = fail

    async def put(self, uri, data, content_type):
        if self.fail:
            raise OSError("minio down")
        self.put_calls.append((uri, data, content_type))


async def test_the_report_is_copied_beside_its_pdf_as_json() -> None:
    objects, incident = Objects(), uuid.uuid4()
    w = worker()
    w._footage = objects
    uri = await w._keep_report(incident, {"incident_id": str(incident), "report": {"title": "é"}})
    assert uri == f"s3://vms-reports/incidents/{incident}/report.json"
    (put_uri, body, content_type) = objects.put_calls[0]
    assert put_uri == uri and content_type == "application/json"
    assert json.loads(body)["report"]["title"] == "é" and "é".encode() in body  # not é


async def test_a_copy_that_cannot_be_written_leaves_the_report_without_one() -> None:
    w = worker()
    w._footage = Objects(fail=True)
    assert await w._keep_report(uuid.uuid4(), {"x": 1}) is None  # and does not raise


# ---- the Redis side -----------------------------------------------------------------------------


class Client:
    def __init__(self, error: Exception | None = None) -> None:
        self.published: list[tuple[str, str]] = []
        self.error = error

    async def publish(self, channel, payload):
        if self.error:
            raise self.error
        self.published.append((channel, payload))
        return 1


async def test_the_notifier_publishes_the_envelope_to_the_channel_the_api_listens_on() -> None:
    client = Client()
    message = WsMessage(type="job.progress", data={"x": 1})
    assert await RedisNotifier(client).send(message) is True
    channel, payload = client.published[0]
    assert channel == "vms:ws:broadcast" and WsMessage.model_validate_json(payload).data == {"x": 1}


@pytest.mark.parametrize("error", [RedisConnectionError("down"), OSError("reset")])
async def test_the_notifier_swallows_a_redis_failure_and_says_so(error: Exception) -> None:
    assert await RedisNotifier(Client(error)).send(WsMessage(type="t", data={})) is False


async def test_the_notifier_does_not_hide_a_programming_error() -> None:
    with pytest.raises(TypeError):
        await RedisNotifier(Client(TypeError("bug"))).send(WsMessage(type="t", data={}))


# ---- the two moments that happen inside a job ---------------------------------------------------


class Linking(Store):
    def __init__(self) -> None:
        super().__init__()
        self.linked: list[tuple] = []
        self.finished: list[tuple] = []

    async def attach_incident(self, job_id, incident_id):
        self.linked.append((job_id, incident_id))

    async def finish(self, job_id, *, failed=None):
        self.finished.append((job_id, failed))


async def test_once_the_report_row_exists_the_job_is_linked_and_progress_names_it() -> None:
    notes, store, j, incident = Notes(), Linking(), job(), uuid.uuid4()
    w = worker(notes, store)
    w._incident = incident
    await w._step(j, "gathering events", 0.03)
    await w._attach(j, incident)
    await w._step(j, "collecting footage", 0.08)
    assert store.linked == [(j.id, incident)]
    assert [data(m).incident_id for m in notes.sent] == [None, str(incident)]


async def test_a_generated_report_closes_the_job_announces_it_and_says_done() -> None:
    notes, store, j, incident = Notes(), Linking(), job(), uuid.uuid4()
    w = worker(notes, store)
    w._incident, w._attached = incident, True
    await w._finish_generated(j, incident, str(j.group_id), "high", "Person climbs the fence", 4)
    assert store.finished == [(j.id, None)]
    assert [m.type for m in notes.sent] == ["incident.ready", "job.progress"]
    last = data(notes.sent[-1])
    assert (last.status, last.fraction, last.incident_id) == ("done", 1.0, str(incident))
