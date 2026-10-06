from types import SimpleNamespace

from vms_common.kafka.dlq_replay import parse, plan


def _record(origin, error="boom", attempts="3", offset=0):
    headers = []
    if origin:
        headers.append(("x-origin-topic", origin.encode()))
    headers += [("x-error", error.encode()), ("x-attempts", attempts.encode())]
    return SimpleNamespace(headers=headers, key=b"k", value=b"{}", partition=0, offset=offset)


def test_headers_are_read_with_defaults_for_missing_or_malformed_ones():
    d = parse(_record("vms.twin.v1", attempts="3"))
    assert (d.origin_topic, d.error, d.attempts) == ("vms.twin.v1", "boom", 3)
    odd = parse(SimpleNamespace(headers=None, key=None, value=b"x", partition=1, offset=7))
    assert odd.origin_topic is None and odd.attempts == 0 and odd.error == ""


def test_plan_filters_by_topic_skips_letters_with_no_origin_and_honours_the_limit():
    letters = [
        parse(_record("vms.twin.v1", offset=0)),
        parse(_record("vms.events.v1", offset=1)),
        parse(_record(None, offset=2)),  # a letter that does not say where it came from
        parse(_record("vms.twin.v1", offset=3)),
    ]
    assert [d.offset for d in plan(letters, topic="vms.twin.v1", limit=None)] == [0, 3]
    assert [d.offset for d in plan(letters, topic=None, limit=None)] == [0, 1, 3]
    assert [d.offset for d in plan(letters, topic=None, limit=2)] == [0, 1]
