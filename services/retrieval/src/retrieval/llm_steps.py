"""The two model calls in a search: decompose the query, rerank the candidates. Both go through
the gateway (CLAUDE.md), both are text tasks, and both fail soft — the caller falls back to the
heuristic plan / the fused order."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from vms_common.contracts.search import QueryEntity, QueryPlan, QuerySpatial
from vms_common.llm import Gateway, render_prompt

from retrieval.domain.rerank import RerankBatch, RerankItem

DECOMPOSE_VERSION = "1.0"
RERANK_VERSION = "1.1"


class _DraftEntity(BaseModel):
    id: str = "e1"
    category: str
    attributes: dict[str, str] = Field(default_factory=dict)


class PlanDraft(BaseModel):
    """What the model is asked for — flatter than `QueryPlan`, which a 3B model fills badly."""

    entities: list[_DraftEntity] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    zones: list[str] = Field(default_factory=list)
    visual_queries: list[str] = Field(default_factory=list)
    text_queries: list[str] = Field(default_factory=list)
    sub_questions: list[str] = Field(default_factory=list)
    event_types_hint: list[str] = Field(default_factory=list)


async def decompose(
    gateway: Gateway, query: str, *, now: datetime, tz: ZoneInfo, zones: list[str]
) -> QueryPlan:
    prompt = render_prompt(
        "query_decompose",
        DECOMPOSE_VERSION,
        query=query,
        now=now.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
        tz=str(tz),
        zones=", ".join(zones),
    )
    result = await gateway.chat(
        "query_decompose", [{"role": "user", "content": prompt}], response_model=PlanDraft
    )
    draft = result.parsed
    assert isinstance(draft, PlanDraft)  # noqa: S101 - validated by the gateway
    return QueryPlan(
        original=query,
        entities=[
            QueryEntity(id=e.id, category=e.category, attributes=e.attributes)
            for e in draft.entities
        ],
        actions=draft.actions[:4],
        spatial=QuerySpatial(zones=draft.zones),
        visual_queries=draft.visual_queries[:3],
        text_queries=draft.text_queries[:2],
        sub_questions=draft.sub_questions[:3],
        event_types_hint=draft.event_types_hint,
        source="llm",
    )


async def rerank_batch(
    gateway: Gateway, *, query: str, sub_questions: list[str], candidates_text: str
) -> list[RerankItem]:
    prompt = render_prompt(
        "rerank",
        RERANK_VERSION,
        query=query,
        sub_questions=sub_questions,
        candidates=candidates_text,
    )
    result = await gateway.chat(
        "rerank", [{"role": "user", "content": prompt}], response_model=RerankBatch
    )
    batch = result.parsed
    assert isinstance(batch, RerankBatch)  # noqa: S101
    return batch.results
