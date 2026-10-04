"""The search pipeline (design §10.1): plan → encode → coarse retrieval → fuse → group →
(reason mode) reread with the twin → respond. Each stage is timed; each model-dependent stage
degrades to the previous stage's answer rather than failing the search."""

from __future__ import annotations

import asyncio
import uuid
from collections import OrderedDict
from datetime import UTC, datetime
from time import perf_counter
from zoneinfo import ZoneInfo

from vms_common.contracts.search import (
    QueryPlan,
    SearchFilters,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from vms_common.llm import Gateway, LLMError
from vms_common.logging import get_logger

from retrieval import llm_steps
from retrieval.adapters.catalog import Catalog
from retrieval.adapters.encoder import SiglipQueryEncoder
from retrieval.adapters.knowledge import KnowledgeSearch
from retrieval.adapters.twins import TwinReader, excerpt_lines
from retrieval.adapters.vectors import VectorSearch
from retrieval.domain.fusion import Hit, Window, group_windows
from retrieval.domain.plan import (
    finalize_plan,
    heuristic_plan,
    plan_categories,
    plan_colors,
)
from retrieval.domain.rerank import RerankItem, blend, format_candidate
from retrieval.settings import RetrievalSettings

log = get_logger(__name__)


def _dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


class SearchPipeline:
    def __init__(
        self,
        *,
        settings: RetrievalSettings,
        encoder: SiglipQueryEncoder,
        vectors: VectorSearch,
        catalog: Catalog,
        twins: TwinReader,
        gateway: Gateway,
        profile: str,
        knowledge: KnowledgeSearch | None = None,
    ) -> None:
        self._s = settings
        self._encoder = encoder
        self._vectors = vectors
        self._catalog = catalog
        self._twins = twins
        self._knowledge = knowledge
        self.recent: OrderedDict[tuple[str, str], tuple[str | None, list[str], list[str]]] = (
            OrderedDict()
        )
        self._gateway = gateway
        self._profile = profile
        self._tz = ZoneInfo(settings.site_timezone)
        self._zones: list[str] = []

    async def _knowledge_hits(self, plan, cameras, start, end) -> list[Hit]:
        """Captions and incident sections by meaning + words; a failure costs only this list."""
        try:
            assert self._knowledge is not None  # noqa: S101
            return await self._knowledge.hits(
                " ".join(plan.text_queries) or plan.original,
                cameras=cameras,
                start=start,
                end=end,
                limit=20,
            )
        except Exception as exc:
            log.warning("knowledge_search_failed", error=str(exc))
            return []

    def _remember(self, search_id: str, results: list[SearchResult]) -> None:
        """What each recent result looked at (its keyframe, segments, tracks), so a mask can be
        asked for by `(search_id, result_id)` without the browser ever holding an s3:// uri."""
        for r in results[:30]:
            self.recent[(search_id, r.result_id)] = (
                r.keyframe_uri,
                list(r.segment_ids),
                list(r.matched_track_ids),
            )
        while len(self.recent) > 600:
            self.recent.popitem(last=False)

    @property
    def catalog(self) -> Catalog:
        return self._catalog

    def _floor(self, start: datetime | None) -> datetime | None:
        """No search reaches back past `archive_since` (see the setting)."""
        floor = self._s.archive_since
        if floor is None:
            return start
        return floor if start is None else max(start, floor)

    async def refresh_zones(self) -> None:
        try:
            self._zones = await self._catalog.known_zones()
        except Exception as exc:  # the vocabulary is an optimisation
            log.warning("zone_vocabulary_unavailable", error=str(exc))

    # --- text ---------------------------------------------------------------------------

    async def text(self, req: SearchRequest, *, user_id: str | None = None) -> SearchResponse:
        timings: dict[str, float] = {}
        notes: list[str] = []
        now = datetime.now(UTC)

        t = perf_counter()
        plan = heuristic_plan(req.query, now=now, tz=self._tz, known_zones=self._zones)
        if req.mode == "reason":
            try:
                llm_plan = await asyncio.wait_for(
                    llm_steps.decompose(
                        self._gateway, req.query, now=now, tz=self._tz, zones=self._zones
                    ),
                    self._s.decompose_budget_s,
                )
                plan = finalize_plan(llm_plan, now=now, tz=self._tz, known_zones=self._zones)
            except (LLMError, TimeoutError) as exc:
                notes.append(f"query decomposition skipped ({type(exc).__name__}); used keywords")
                plan = finalize_plan(plan, now=now, tz=self._tz, known_zones=self._zones)
        else:
            plan = finalize_plan(plan, now=now, tz=self._tz, known_zones=self._zones)
        timings["plan"] = _ms_since(t)

        cameras = req.filters.cameras or plan.spatial.cameras
        start = req.filters.start or plan.temporal.start
        end = req.filters.end or plan.temporal.end
        start = self._floor(start)

        t = perf_counter()
        queries = list(dict.fromkeys([*plan.visual_queries[:3], plan.original]))
        vectors = await asyncio.to_thread(self._encoder.embed_text, queries)
        timings["encode"] = _ms_since(t)

        t = perf_counter()
        cats = plan_categories(plan)
        colors = plan_colors(plan)
        n = self._s.hits_per_query
        jobs = []
        for vec in vectors:
            jobs.append(self._vectors.frames(vec, cameras=cameras, start=start, end=end, limit=n))
            jobs.append(
                self._vectors.tracks(
                    vec,
                    cameras=cameras,
                    start=start,
                    end=end,
                    categories=cats,
                    limit=n,
                    prefer_colors=colors,
                    prefer_zones=plan.spatial.zones,
                )
            )
        jobs.append(
            self._catalog.event_hits(
                " ".join(plan.text_queries) or plan.original,
                cameras=cameras,
                start=start,
                end=end,
                event_types=plan.event_types_hint,
                limit=20,
            )
        )
        if self._knowledge is not None and self._knowledge.loaded:
            jobs.append(self._knowledge_hits(plan, cameras, start, end))
        lists: list[list[Hit]] = [r for r in await asyncio.gather(*jobs)]
        timings["retrieve"] = _ms_since(t)

        t = perf_counter()
        windows = group_windows(
            [lst for lst in lists if lst], window_s=self._s.window_s, top_k=max(req.top_k, 12)
        )
        results = await self._to_results(windows)
        results, expired = await self._drop_expired(windows, results)
        if expired:
            notes.append(
                f"{expired} older match{'es' if expired > 1 else ''} hidden: "
                "the recording has been removed by the retention policy"
            )
        timings["fuse"] = _ms_since(t)

        if req.mode == "reason" and results:
            t = perf_counter()
            results = await self._reason(req.query, plan, windows, results, notes)
            timings["rerank"] = _ms_since(t)
        results = results[: req.top_k]
        if not results:
            notes.append("nothing in the archive matched; try fewer details or a wider time range")

        search_id = str(uuid.uuid4())
        self._remember(search_id, results)
        response = SearchResponse(
            search_id=search_id,
            query=req.query,
            mode=req.mode,
            profile=self._profile,
            plan=plan,
            results=results,
            timings_ms={**timings, "total": round(sum(timings.values()), 1)},
            notes=notes,
        )
        await self._log(response, kind="text", user_id=user_id)
        return response

    # --- image --------------------------------------------------------------------------

    async def image(
        self,
        data: bytes,
        *,
        filters: SearchFilters,
        top_k: int,
        label: str,
        user_id: str | None = None,
    ) -> SearchResponse:
        timings: dict[str, float] = {}
        t = perf_counter()
        vec = await asyncio.to_thread(self._encoder.embed_image, data)
        timings["encode"] = _ms_since(t)
        t = perf_counter()
        hits = await self._vectors.tracks(
            vec,
            cameras=filters.cameras,
            start=self._floor(filters.start),
            end=filters.end,
            categories=[],
            limit=self._s.hits_per_query,
            source="image",
        )
        timings["retrieve"] = _ms_since(t)
        t = perf_counter()
        windows = group_windows([hits], window_s=self._s.window_s, top_k=top_k)
        results = await self._to_results(windows)
        results, expired = await self._drop_expired(windows, results)
        timings["fuse"] = _ms_since(t)
        search_id = str(uuid.uuid4())
        self._remember(search_id, results[:top_k])
        response = SearchResponse(
            search_id=search_id,
            query=label,
            mode="fast",
            kind="image",
            profile=self._profile,
            results=results[:top_k],
            timings_ms={**timings, "total": round(sum(timings.values()), 1)},
            notes=[f"{expired} older matches hidden: the recording has been removed"]
            if expired
            else [],
        )
        await self._log(response, kind="image", user_id=user_id)
        return response

    # --- shared -------------------------------------------------------------------------

    async def _to_results(self, windows: list[Window]) -> list[SearchResult]:
        events = await asyncio.gather(
            *(self._catalog.events_in(w.camera_id, w.start_ms, w.end_ms) for w in windows),
            return_exceptions=True,
        )
        keyframes = await asyncio.gather(
            *(
                self._vectors.keyframe_near(w.camera_id, (w.start_ms + w.end_ms) // 2)
                if not any(h.keyframe_uri for h in w.hits)
                else _none()
                for w in windows
            ),
            return_exceptions=True,
        )
        out: list[SearchResult] = []
        for w, evs, kf in zip(windows, events, keyframes, strict=True):
            frames = sorted((h for h in w.hits if h.keyframe_uri), key=lambda h: -h.cosine)
            tracks = sorted((h for h in w.hits if h.crop_uri), key=lambda h: -h.cosine)
            ev_rows = evs if isinstance(evs, list) else []
            caption = next((h.caption for h in w.hits if h.caption), None) or next(
                (e["caption"] for e in ev_rows if e.get("caption")), None
            )
            keyframe = frames[0].keyframe_uri if frames else (kf if isinstance(kf, str) else None)
            out.append(
                SearchResult(
                    result_id=w.result_id,
                    camera_id=w.camera_id,
                    segment_ids=list(dict.fromkeys(s for h in w.hits for s in h.segment_ids)),
                    start_ts=_dt(w.start_ms),
                    end_ts=_dt(max(w.end_ms, w.start_ms + 2000)),
                    score=w.score,
                    fused_score=w.score,
                    keyframe_uri=keyframe,
                    crop_uris=list(dict.fromkeys(h.crop_uri for h in tracks if h.crop_uri))[:4],
                    matched_track_ids=list(dict.fromkeys(h.track_id for h in tracks if h.track_id))[
                        :12
                    ],
                    categories=sorted({h.category for h in w.hits if h.category}),
                    colors=sorted({c for h in w.hits for c in h.colors}),
                    zones=sorted({z for h in w.hits for z in h.zones}),
                    incident_ids=list(
                        dict.fromkeys(h.incident_id for h in w.hits if h.incident_id)
                    ),
                    event_ids=list(
                        dict.fromkeys(
                            [h.event_id for h in w.hits if h.event_id] + [e["id"] for e in ev_rows]
                        )
                    ),
                    caption=caption,
                    sources=sorted({h.source for h in w.hits}),  # type: ignore[misc]
                )
            )
        return out

    async def _drop_expired(
        self, windows: list[Window], results: list[SearchResult]
    ) -> tuple[list[SearchResult], int]:
        """Results whose picture is gone (retention deletes keyframes and recordings after a
        few days while the index outlives them) are not shown: a card with nothing behind it
        cannot be opened in playback either. `windows` is filtered in step so the two lists
        keep their positions."""
        alive = await asyncio.gather(
            *(self._twins.exists(r.keyframe_uri) if r.keyframe_uri else _true() for r in results)
        )
        keep = [i for i, ok in enumerate(alive) if ok]
        windows[:] = [windows[i] for i in keep]
        return [results[i] for i in keep], len(results) - len(keep)

    async def _reason(
        self,
        query: str,
        plan: QueryPlan,
        windows: list[Window],
        results: list[SearchResult],
        notes: list[str],
    ) -> list[SearchResult]:
        top = results[: self._s.rerank_top_n]
        try:
            scored = await asyncio.wait_for(
                self._rerank(query, plan, windows[: len(top)], top), self._s.llm_budget_s
            )
        except (LLMError, TimeoutError) as exc:
            notes.append(f"reasoning rerank skipped ({type(exc).__name__}); showing fused order")
            return results
        if not scored:
            notes.append("reasoning rerank returned nothing usable; showing fused order")
            return results

        w = self._s.reasoning_weight
        merged: list[SearchResult] = []
        for r in results:
            item = scored.get(r.result_id)
            if item is None:
                merged.append(r)
                continue
            merged.append(
                r.model_copy(
                    update={
                        "reasoning_score": item.score,
                        "trace": item.trace or None,
                        "missing": item.missing[:3],
                        "score": blend(r.fused_score, item.score, w),
                    }
                )
            )
        # Candidates the model never saw keep their fused score but must not outrank ones it
        # judged to be good matches: cap them at the lowest judged blend.
        judged = [m.score for m in merged if m.reasoning_score is not None]
        floor = min(judged) if judged else 1.0
        merged = [
            m
            if m.reasoning_score is not None
            else m.model_copy(update={"score": min(m.score, floor)})
            for m in merged
        ]
        merged.sort(key=lambda m: (-m.score, m.start_ts))
        return merged

    async def _rerank(
        self,
        query: str,
        plan: QueryPlan,
        windows: list[Window],
        results: list[SearchResult],
    ) -> dict[str, RerankItem]:
        seg_ids = list({s for r in results for s in r.segment_ids})
        uris = await self._catalog.twin_uris(seg_ids)
        twins = await self._twins.load_many(list(uris.values()))
        by_seg = {sid: twins[u] for sid, u in uris.items() if u in twins}

        blocks: dict[str, str] = {}
        for i, (w, r) in enumerate(zip(windows, results, strict=True), start=1):
            lines = excerpt_lines(
                [by_seg[s] for s in r.segment_ids if s in by_seg],
                start_ms=w.start_ms,
                end_ms=w.end_ms,
                track_ids=set(r.matched_track_ids),
            )
            if r.caption:
                lines.insert(0, f"event description: {r.caption}")
            when = r.start_ts.astimezone(self._tz).strftime("%d %b %H:%M:%S")
            blocks[f"c{i}"] = format_candidate(
                f"c{i}", camera=r.camera_id, when=when, lines=lines[:8]
            )
        ids = {f"c{i}": r.result_id for i, r in enumerate(results, start=1)}

        keys = list(blocks)
        size = self._s.rerank_batch
        batches = [keys[i : i + size] for i in range(0, len(keys), size)]

        async def one(batch: list[str]) -> list[RerankItem]:
            try:
                return await llm_steps.rerank_batch(
                    self._gateway,
                    query=query,
                    sub_questions=plan.sub_questions,
                    candidates_text="\n".join(blocks[k] for k in batch),
                )
            except LLMError as exc:
                log.warning("rerank_batch_failed", error=str(exc))
                return []

        scored: dict[str, RerankItem] = {}
        # Sequential: the GPU lease serialises local calls anyway, and two 8k-context requests
        # queued at once only add memory pressure.
        for batch in batches:
            for item in await one(batch):
                rid = ids.get(item.id.strip().strip("[]").lower())
                if rid:
                    scored[rid] = item
        return scored

    async def _log(self, response: SearchResponse, *, kind: str, user_id: str | None) -> None:
        try:
            await self._catalog.log_search(
                search_id=response.search_id,
                user_id=user_id,
                kind=kind,
                query=response.query,
                mode=response.mode,
                profile=response.profile,
                plan=response.plan.model_dump(mode="json") if response.plan else None,
                results=[
                    {"id": r.result_id, "camera": r.camera_id, "score": r.score}
                    for r in response.results
                ],
                timings=response.timings_ms,
            )
        except Exception as exc:  # the log must never fail a search
            log.warning("search_log_failed", error=str(exc))


async def _none() -> None:
    return None


async def _true() -> bool:
    return True


def _ms_since(t: float) -> float:
    return round((perf_counter() - t) * 1000, 1)
