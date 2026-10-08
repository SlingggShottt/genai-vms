"""The base consumer's metrics: how far behind its group is, and what it gave up on."""

import asyncio

import pytest
from aiokafka import TopicPartition
from vms_common.kafka.consumer import (
    BaseConsumer,
    consumer_lag,
    dead_letters,
    lag_by_topic,
    partition_lag,
)


class _FakeAIOKafka:
    def __init__(self, ends, committed, beginnings=None):
        self._ends, self._committed = ends, committed
        self._beginnings = beginnings or {tp: 0 for tp in ends}

    def assignment(self):
        return set(self._ends)

    async def end_offsets(self, parts):
        return {tp: self._ends[tp] for tp in parts}

    async def beginning_offsets(self, parts):
        return {tp: self._beginnings[tp] for tp in parts}

    async def committed(self, tp):
        return self._committed.get(tp)


def test_a_partition_is_as_far_behind_as_the_gap_to_its_end():
    assert partition_lag(end=120, committed=100, beginning=0) == 20
    assert partition_lag(end=100, committed=100, beginning=0) == 0
    assert partition_lag(end=90, committed=100, beginning=0) == 0  # never negative


def test_a_group_that_has_never_committed_is_behind_by_the_whole_partition():
    assert partition_lag(end=50, committed=None, beginning=10) == 40


def test_lag_is_summed_per_topic_over_the_assigned_partitions():
    a, b, c = TopicPartition("t.one", 0), TopicPartition("t.one", 1), TopicPartition("t.two", 0)
    fake = _FakeAIOKafka(
        ends={a: 100, b: 50, c: 7}, committed={a: 90, c: 7}, beginnings={a: 0, b: 20, c: 0}
    )
    assert asyncio.run(lag_by_topic(fake)) == {"t.one": 10 + 30, "t.two": 0}


def test_no_assignment_is_no_lag():
    assert asyncio.run(lag_by_topic(_FakeAIOKafka({}, {}))) == {}


class _Consumer(BaseConsumer):
    async def handle(self, message, record):  # pragma: no cover - not reached
        return None


@pytest.mark.parametrize("broken", [False, True])
def test_the_reporter_sets_the_gauge_and_survives_a_broker_error(monkeypatch, broken):
    tp = TopicPartition("vms.twin.v1", 0)
    group = "g-lag-broken" if broken else "g-lag-ok"  # the gauge is process-wide
    c = _Consumer(topic="vms.twin.v1", group_id=group, bootstrap_servers="x", model=object)
    c._consumer = _FakeAIOKafka({tp: 30}, {tp: 5})
    if broken:

        async def boom(_):
            raise OSError("broker unreachable")

        monkeypatch.setattr("vms_common.kafka.consumer.lag_by_topic", boom)

    async def one_round():
        task = asyncio.create_task(c._report_lag())
        await asyncio.sleep(0.05)
        assert not task.done()  # an error is swallowed, the loop goes on
        task.cancel()

    asyncio.run(one_round())
    value = consumer_lag.labels(group=group, topic="vms.twin.v1")._value.get()
    assert value == (0 if broken else 25)


def test_the_reporter_stops_when_the_consumer_loop_ends():
    class _Ends(_FakeAIOKafka):
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration  # the topic loop ends at once

    c = _Consumer(topic="t", group_id="g-lag-end", bootstrap_servers="x", model=object)
    c._consumer = _Ends({}, {})

    async def scenario():
        await c.run()
        await asyncio.sleep(0)  # let a cancelled task finish
        return [t for t in asyncio.all_tasks() if "_report_lag" in repr(t.get_coro())]

    assert asyncio.run(scenario()) == []


def test_a_dead_lettered_message_is_counted_once_it_is_sent():
    class _Producer:
        def __init__(self):
            self.sent = []

        async def send_and_wait(self, topic, **kw):
            self.sent.append(topic)

    class _Record:
        topic, offset, value, key = "vms.twin.v1", 7, b"{}", None

    c = _Consumer(topic="vms.twin.v1", group_id="g-dlq", bootstrap_servers="x", model=object)
    c._dlq_producer = _Producer()
    counter = dead_letters.labels(group="g-dlq", topic="vms.twin.v1")
    before = counter._value.get()
    asyncio.run(c._to_dlq(_Record(), ValueError("bad"), attempts=3))
    assert c._dlq_producer.sent == ["vms.dlq.v1"] and counter._value.get() == before + 1

    class _Failing(_Producer):
        async def send_and_wait(self, topic, **kw):
            raise OSError("broker down")

    c._dlq_producer = _Failing()
    with pytest.raises(OSError):
        asyncio.run(c._to_dlq(_Record(), ValueError("bad"), attempts=3))
    assert counter._value.get() == before + 1  # not counted: it did not reach the topic
