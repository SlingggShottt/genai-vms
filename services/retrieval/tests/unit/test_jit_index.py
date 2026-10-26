"""P4-J3: a picture check the vision model answered "yes" to is written into `knowledge`, and read
back as a hit on later searches. Fakes only: no model, no Qdrant, no database."""

from __future__ import annotations

import types
from datetime import UTC, datetime, timedelta

import pytest
from retrieval import jit as jit_module
from retrieval.adapters import knowledge as knowledge_module
from retrieval.jit import JitRefiner, JitVerdict, jit_doc, question_hash
from vms_common.contracts.search import JitAnswerOut, SearchResult
from vms_common.qdrant.knowledge import DOC_JIT

START = datetime(2026, 10, 25, 9, 30, tzinfo=UTC)


def result(**over) -> SearchResult:  # noqa: ANN003
    base = dict(  # noqa: C408
        result_id="r1", camera_id="cam02", segment_ids=["seg-1"], start_ts=START,
        end_ts=START + timedelta(seconds=10), score=0.8, fused_score=0.8,
        keyframe_uri="s3://vms-keyframes/cam02/k.jpg", missing=["Is the bag blue?"],
        caption="a person with a bag",
    )  # fmt: skip
    return SearchResult(**{**base, **over})


def answer(verdict: str = "yes", detail: str = "a blue backpack") -> JitAnswerOut:
    return JitAnswerOut(question="Is the bag blue?", answer=verdict, detail=detail)


# ---- the document ---------------------------------------------------------------------------


def test_a_yes_becomes_a_document_with_the_footage_it_is_about() -> None:
    doc = jit_doc(result(), "seg-1", answer())

    assert doc is not None
    assert doc.text == (
        "Confirmed in the picture on cam02 at 2026-10-25T09:30:00+00:00: "
        "Is the bag blue? Yes. a blue backpack"
    )
    assert doc.payload["doc_type"] == DOC_JIT and doc.payload["ref_id"] == "seg-1"
    assert doc.payload["camera_ids"] == ["cam02"]
    assert doc.payload["ts_start"] == int(START.timestamp() * 1000)
    assert doc.payload["ts_end"] == int((START + timedelta(seconds=10)).timestamp() * 1000)
    assert doc.payload["part"] == question_hash("Is the bag blue?")


@pytest.mark.parametrize("verdict", ["no", "unsure"])
def test_only_a_yes_is_indexed_because_a_no_would_be_found_by_the_queries_it_rules_out(
    verdict: str,
) -> None:
    assert jit_doc(result(), "seg-1", answer(verdict)) is None


def test_the_same_question_about_the_same_footage_is_the_same_point() -> None:
    a = jit_doc(result(), "seg-1", answer())
    b = jit_doc(result(), "seg-1", JitAnswerOut(question="is the BAG blue", answer="yes"))
    other_segment = jit_doc(result(), "seg-2", answer())
    assert a is not None and b is not None and other_segment is not None
    assert a.point_id == b.point_id != other_segment.point_id


# ---- the refiner writes it, once, and never fails a search over it ---------------------------


class FakeGateway:
    def __init__(self, verdict: str) -> None:
        self.calls = 0
        self._verdict = verdict

    async def vision(self, task, prompt, images, *, response_model):  # noqa: ANN001, ANN201
        self.calls += 1
        return types.SimpleNamespace(
            parsed=JitVerdict(answer=self._verdict, detail="a blue backpack"),
            provider="ollama",
            model="qwen2.5vl:3b",
        )


class FakeS3:
    async def get_bytes(self, uri: str) -> bytes:
        return b"jpeg"


def refiner(verdict: str, index, *, cached: JitAnswerOut | None = None):  # noqa: ANN001, ANN201
    r = JitRefiner(FakeGateway(verdict), None, FakeS3(), index=index)  # type: ignore[arg-type]
    stored: list[str] = []

    async def no_cache(segment: str, qhash: str) -> JitAnswerOut | None:
        return cached

    async def keep(segment, qhash, uri, ans, model) -> None:  # noqa: ANN001
        stored.append(qhash)

    r._cached, r._store = no_cache, keep  # type: ignore[method-assign]
    return r, stored


async def test_a_fresh_yes_is_stored_and_indexed() -> None:
    indexed = []

    async def index(doc) -> None:  # noqa: ANN001
        indexed.append(doc)

    r, stored = refiner("yes", index)
    got = await r._ask(result(), "Is the bag blue?", "ctx")

    assert got is not None and got.answer == "yes"
    assert len(stored) == 1 and len(indexed) == 1
    assert indexed[0].payload["doc_type"] == DOC_JIT


async def test_a_no_is_stored_for_the_cache_but_not_indexed() -> None:
    indexed = []

    async def index(doc) -> None:  # noqa: ANN001
        indexed.append(doc)

    r, stored = refiner("no", index)
    await r._ask(result(), "Is the bag blue?", "ctx")

    assert len(stored) == 1 and indexed == []


async def test_a_cached_answer_is_not_asked_or_indexed_again() -> None:
    indexed = []

    async def index(doc) -> None:  # noqa: ANN001
        indexed.append(doc)

    r, _ = refiner("yes", index, cached=answer())
    got = await r._ask(result(), "Is the bag blue?", "ctx")

    assert got is not None and r._gateway.calls == 0 and indexed == []  # type: ignore[attr-defined]


async def test_an_index_that_fails_does_not_fail_the_search() -> None:
    async def broken(doc) -> None:  # noqa: ANN001
        raise ConnectionError("qdrant is down")

    r, stored = refiner("yes", broken)
    got = await r._ask(result(), "Is the bag blue?", "ctx")

    assert got is not None and got.answer == "yes" and len(stored) == 1


# ---- reading it back ------------------------------------------------------------------------


async def test_a_picture_check_comes_back_as_a_hit_that_carries_no_caption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = {}

    async def fake_search(client, embedder, query, **kwargs):  # noqa: ANN001, ANN003, ANN202
        seen.update(kwargs)
        payload = {
            "doc_type": DOC_JIT, "ref_id": "seg-1", "part": "abc", "camera_ids": ["cam02"],
            "ts_start": 1000, "ts_end": 11000, "keyframe_uri": "s3://k/1.jpg",
            "text": "Confirmed in the picture ...",
        }  # fmt: skip
        return [types.SimpleNamespace(payload=payload, score=0.7)]

    monkeypatch.setattr(knowledge_module, "search_docs", fake_search)
    search = knowledge_module.KnowledgeSearch(None, None)  # type: ignore[arg-type]

    hits = await search.hits("blue bag", cameras=[], start=None, end=None, limit=10)

    assert DOC_JIT in seen["doc_types"]
    assert len(hits) == 1
    hit = hits[0]
    assert hit.key == "j:seg-1:abc" and hit.camera_id == "cam02"
    assert hit.caption is None and hit.event_id is None  # it must not replace a real caption
    assert (hit.start_ms, hit.end_ms) == (1000, 11000) and hit.keyframe_uri == "s3://k/1.jpg"


def test_the_jit_budget_defaults_to_the_designs_eight_seconds() -> None:
    from retrieval.settings import RetrievalSettings

    assert RetrievalSettings().jit_budget_s == 8.0 and RetrievalSettings().candidate_pool == 30
    assert jit_module.PROMPT_VERSION  # the module imports cleanly with the new dependencies
