"""queryplan.v1 and the search request/response (design_architecture.md §10.1).

Retrieval produces these; the api forwards them to the browser, so they live here rather than
in a service. The plan is what the LLM decomposition returned (or what the heuristic fallback
built when no model could be reached); the response carries it so the UI can show *how* the
query was understood, alongside the per-stage timings.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

SearchMode = Literal["fast", "reason"]


class QueryEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    category: str
    attributes: dict[str, str] = Field(default_factory=dict)


class QueryRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    predicate: str
    object: str | None = None


class QuerySpatial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zones: list[str] = Field(default_factory=list)
    cameras: list[str] = Field(default_factory=list)


class QueryTemporal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: AwareDatetime | None = None
    end: AwareDatetime | None = None


class QueryPlan(BaseModel):
    """`queryplan.v1`. Every list may be empty: a vague query still gets a plan."""

    model_config = ConfigDict(extra="ignore")

    schema_version: Literal["queryplan.v1"] = "queryplan.v1"
    original: str
    entities: list[QueryEntity] = Field(default_factory=list)
    relations: list[QueryRelation] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    spatial: QuerySpatial = Field(default_factory=QuerySpatial)
    temporal: QueryTemporal = Field(default_factory=QueryTemporal)
    visual_queries: list[str] = Field(default_factory=list, max_length=4)
    text_queries: list[str] = Field(default_factory=list, max_length=4)
    sub_questions: list[str] = Field(default_factory=list, max_length=4)
    event_types_hint: list[str] = Field(default_factory=list)
    source: Literal["llm", "heuristic"] = "llm"


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cameras: list[str] = Field(default_factory=list)
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=500)
    mode: SearchMode = "fast"
    filters: SearchFilters = Field(default_factory=SearchFilters)
    top_k: int = Field(default=12, ge=1, le=30)
    jit: bool = Field(
        default=False,
        description="reason mode only: let a vision model check missing facts in the picture",
    )


class JitAnswerOut(BaseModel):
    """A fact a vision model checked in the result's keyframe (design §10.1 JIT refinement)."""

    model_config = ConfigDict(extra="forbid")

    question: str
    answer: Literal["yes", "no", "unsure"]
    detail: str = ""
    cached: bool = False


class SearchResult(BaseModel):
    """One ranked window of footage. `reasoning_score`/`trace` are set in `reason` mode."""

    model_config = ConfigDict(extra="forbid")

    result_id: str
    camera_id: str
    segment_ids: list[str]
    start_ts: AwareDatetime
    end_ts: AwareDatetime
    score: float = Field(ge=0, le=1, description="what the ranking uses")
    fused_score: float = Field(ge=0, le=1)
    reasoning_score: float | None = Field(default=None, ge=0, le=1)
    trace: str | None = None
    missing: list[str] = Field(default_factory=list)
    jit_answers: list[JitAnswerOut] = Field(default_factory=list)
    keyframe_uri: str | None = None
    crop_uris: list[str] = Field(default_factory=list)
    matched_track_ids: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    zones: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    incident_ids: list[str] = Field(default_factory=list)
    caption: str | None = None
    sources: list[Literal["frames", "tracks", "events", "image"]] = Field(default_factory=list)


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    search_id: str
    query: str
    mode: SearchMode
    kind: Literal["text", "image"] = "text"
    profile: str
    plan: QueryPlan | None = None
    results: list[SearchResult]
    timings_ms: dict[str, float] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list, description="degradations, e.g. rerank skipped")
