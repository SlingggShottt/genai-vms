"""Just-in-time refinement (design §10.1, P4-J3): the rerank says what the records could not tell
("is the bag blue?"); a vision model looks at the result's keyframe and answers, once. Answers are
cached by `(segment, question)` so the same question about the same footage never costs a second
model call, and they come back to the rerank as extra facts.

Opt-in per search: on the 4 GB GPU a text→vision model swap alone takes ~20 s."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import text
from vms_common.contracts.search import JitAnswerOut, SearchResult
from vms_common.llm import Gateway, ImageInput, LLMError, render_prompt
from vms_common.logging import get_logger
from vms_common.qdrant.knowledge import DOC_JIT, KnowledgeDoc
from vms_common.qdrant.point_ids import knowledge_point_id
from vms_common.storage.s3 import S3Client

from retrieval.adapters.catalog import Catalog

log = get_logger(__name__)

PROMPT_VERSION = "1.0"


class JitVerdict(BaseModel):
    answer: Literal["yes", "no", "unsure"]
    detail: str = Field(default="", max_length=300)


def askable(missing: list[str]) -> list[str]:
    """Only real questions go to the vision model. A model asked to "list what is unknown" often
    writes statements ("No information about the colour"), and a vision model told to answer
    one says "yes"."""
    return [
        q.strip()
        for q in missing
        if q.strip().endswith("?") and len(q.split()) >= 3 and len(q) <= 200
    ]


def question_hash(question: str) -> str:
    norm = re.sub(r"\W+", " ", question.lower()).strip()
    return hashlib.sha1(norm.encode()).hexdigest()  # noqa: S324 - a cache key, not a secret


def jit_doc(result: SearchResult, segment: str, answer: JitAnswerOut) -> KnowledgeDoc | None:
    """What a picture check adds to the `knowledge` index, so that a later search for the same
    thing finds the footage without asking the vision model again. Only a "yes" is indexed: the
    text is matched by meaning and by words, so a "no" ("is the bag blue? no") would be found by
    exactly the queries it rules out, and an "unsure" says nothing."""
    if answer.answer != "yes":
        return None
    when = result.start_ts.isoformat(timespec="seconds")
    detail = f" {answer.detail}" if answer.detail else ""
    qhash = question_hash(answer.question)
    return KnowledgeDoc(
        point_id=knowledge_point_id(DOC_JIT, segment, qhash),
        text=f"Confirmed in the picture on {result.camera_id} at {when}: "
        f"{answer.question.rstrip('?')}? Yes.{detail}",
        payload={
            "doc_type": DOC_JIT,
            "ref_id": segment,
            "part": qhash,
            "camera_ids": [result.camera_id],
            "ts_start": int(result.start_ts.timestamp() * 1000),
            "ts_end": int(result.end_ts.timestamp() * 1000),
            "keyframe_uri": result.keyframe_uri,
        },
    )


IndexDoc = Callable[[KnowledgeDoc], Awaitable[None]]


class JitRefiner:
    def __init__(
        self,
        gateway: Gateway,
        catalog: Catalog,
        s3: S3Client,
        *,
        index: IndexDoc | None = None,
    ) -> None:
        self._gateway = gateway
        self._catalog = catalog
        self._s3 = s3
        self._index = index  # where a new "yes" is written for later searches (best effort)

    async def _cached(self, segment_id: str, qhash: str) -> JitAnswerOut | None:
        async with self._catalog.session_factory() as s:
            row = (
                await s.execute(
                    text(
                        "SELECT question, answer, detail FROM retrieval.jit_cache "
                        "WHERE segment_id = :s AND question_hash = :h"
                    ),
                    {"s": segment_id, "h": qhash},
                )
            ).first()
        return (
            JitAnswerOut(question=row[0], answer=row[1], detail=row[2], cached=True)
            if row
            else None
        )

    async def _store(
        self, segment_id: str, qhash: str, uri: str, answer: JitAnswerOut, model: str
    ) -> None:
        async with self._catalog.session_factory() as s, s.begin():
            await s.execute(
                text(
                    "INSERT INTO retrieval.jit_cache (segment_id, question_hash, question, answer, "
                    "detail, keyframe_uri, model) VALUES (:s, :h, :q, :a, :d, :u, :m) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "s": segment_id,
                    "h": qhash,
                    "q": answer.question,
                    "a": answer.answer,
                    "d": answer.detail,
                    "u": uri,
                    "m": model,
                },
            )

    async def _ask(self, result: SearchResult, question: str, context: str) -> JitAnswerOut | None:
        segment = result.segment_ids[0] if result.segment_ids else result.result_id
        qhash = question_hash(question)
        hit = await self._cached(segment, qhash)
        if hit is not None:
            return hit
        if not result.keyframe_uri:
            return None
        try:
            image = await self._s3.get_bytes(result.keyframe_uri)
            prompt = render_prompt(
                "jit_vqa",
                PROMPT_VERSION,
                camera=result.camera_id,
                when=result.start_ts.isoformat(timespec="seconds"),
                context=context,
                question=question,
            )
            out = await self._gateway.vision(
                "jit_vqa", prompt, [ImageInput(data=image)], response_model=JitVerdict
            )
        except LLMError as exc:
            log.warning("jit_failed", error=str(exc))
            return None
        verdict = out.parsed
        assert isinstance(verdict, JitVerdict)  # noqa: S101 - validated by the gateway
        answer = JitAnswerOut(question=question, answer=verdict.answer, detail=verdict.detail)
        await self._store(
            segment, qhash, result.keyframe_uri, answer, f"{out.provider}/{out.model}"
        )
        doc = jit_doc(result, segment, answer)
        if doc is not None and self._index is not None:
            try:
                await self._index(doc)
            except Exception as exc:  # noqa: BLE001 - a search must not fail over its cache
                log.warning("jit_index_failed", error=str(exc))
        return answer

    async def refine(
        self,
        results: list[SearchResult],
        *,
        top_n: int,
        per_candidate: int,
        budget_s: float,
    ) -> dict[str, list[JitAnswerOut]]:
        """Answers for the best `top_n` results that have unanswered questions, within a total
        time budget (a late answer is dropped, never awaited past it)."""
        todo = [r for r in results if askable(r.missing) and r.keyframe_uri][:top_n]
        out: dict[str, list[JitAnswerOut]] = {}

        async def run() -> None:
            # Sequential: the GPU lease serialises local calls and a second concurrent image
            # request only adds memory pressure.
            for r in todo:
                context = r.caption or ", ".join(r.categories + r.colors[:3] + r.zones)
                for q in askable(r.missing)[:per_candidate]:
                    answer = await self._ask(r, q, context)
                    if answer is not None:
                        out.setdefault(r.result_id, []).append(answer)

        try:
            await asyncio.wait_for(run(), budget_s)
        except TimeoutError:
            log.info("jit_budget_spent", answered=sum(len(v) for v in out.values()))
        return out
