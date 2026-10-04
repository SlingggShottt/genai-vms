"""The assistant's turn: decide tool calls (JSON action protocol), run them, then stream an
answer that cites only what the tools returned (design §10.3).

The local model has no native tool calling, so each round asks it for one JSON action
(`tool` or `answer`) validated against `AgentStep`; at most `MAX_CALLS` tools run. The answer
is a second, streamed call over the gathered evidence. Citations in the answer are checked
against what the tools handed out (`Evidence.resolve`); the stream ends with the valid ones and
the list of tags that were not real."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError
from vms_common.llm import Gateway, LLMError, render_prompt
from vms_common.logging import get_logger

from retrieval.assistant.evidence import Evidence
from retrieval.assistant.router import lead_sentence, route
from retrieval.assistant.store import ChatStore, Turn, render_history, split_history
from retrieval.assistant.tools import TOOLS, ToolContext, tool_catalogue
from retrieval.metrics import assistant_turns_total

log = get_logger(__name__)

MAX_CALLS = 4
RESULT_CHARS = 1800  # one tool result, as shown to the model
EVIDENCE_CHARS = 6000  # all of a turn's results together
TASK = "assistant"
VERSIONS = {"agent": "1.0", "answer": "1.1", "summary": "1.0"}


def strip_repeat(text: str, lead: str) -> str:
    """The model's opening with the lead sentence removed if it only said it again (ignoring case,
    quotes and a leading "Answer:" label)."""
    body = text.lstrip()
    for label in ("Answer:", "Answer :", "A:"):
        if body.startswith(label):
            body = body[len(label) :].lstrip()
    quoted = body.startswith('"')
    body = body.lstrip("\"' ")
    norm = lambda t: " ".join(t.lower().rstrip(".").split())  # noqa: E731
    if norm(body[: len(lead) + 1]).startswith(norm(lead)):
        rest = body[len(lead) :].lstrip(" .\"'")
        return rest.rstrip('"') if quoted else rest
    return body


class AgentStep(BaseModel):
    thought: str = ""
    action: Literal["tool", "answer"]
    tool: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)


class Assistant:
    def __init__(
        self,
        *,
        gateway: Gateway,
        store: ChatStore,
        ctx_factory,
        tz: ZoneInfo,
        cameras: list[str],
    ) -> None:
        self._gw = gateway
        self._store = store
        self._ctx_factory = ctx_factory
        self._tz = tz
        self._cameras = cameras
        self._background: set[asyncio.Task] = set()

    async def respond(self, session_id: uuid.UUID, user_text: str) -> AsyncIterator[dict[str, Any]]:
        """Run one turn, yielding stream events (`tool_call`, `tool_result`, `token`,
        `citation`, `done`, `error`). The user message is stored first; the assistant message
        is stored when the stream ends — also when the client stops it (`stopped`)."""
        history_rows = await self._store.messages(session_id)
        await self._store.add(session_id, "user", user_text)
        if not history_rows:
            await self._store.set_title(session_id, user_text.strip().splitlines()[0])
        _older, recent = split_history(history_rows)
        # read fresh: a background update may have landed since the last turn
        summary = await self._summary(session_id)
        history = render_history(recent)

        evidence = Evidence()
        ctx: ToolContext = self._ctx_factory(evidence)
        gathered: list[tuple[str, str]] = []  # (tool call, result text) for the prompt
        tool_log: list[dict[str, Any]] = []
        seen: set[str] = set()
        answer: list[str] = []
        status = "complete"
        citations: list[dict[str, Any]] = []
        message_id: uuid.UUID | None = None

        try:
            now = datetime.now(UTC).astimezone(self._tz).strftime("%A %d %B %Y, %H:%M")
            routed = route(user_text, self._cameras)
            lead: str | None = None
            for _round in range(MAX_CALLS + 1):
                if routed is not None:
                    if gathered:
                        break  # a recognised question needs its one lookup; answer from it
                    step = AgentStep(action="tool", tool=routed[0], arguments=routed[1])
                else:
                    try:
                        step = await self._plan(
                            question=user_text,
                            now=now,
                            summary=summary,
                            history=history,
                            gathered=gathered,
                        )
                    except LLMError as exc:
                        log.warning("assistant_plan_failed", error=str(exc))
                        break
                if step.action == "answer" or len(gathered) >= MAX_CALLS:
                    break
                before = len(evidence)
                call = await self._call(step, ctx, seen)
                if call is None:
                    break
                label, args, result = call
                found = [c.as_json() for c in evidence.all()[before:]]
                yield {"type": "tool_call", "tool": step.tool, "arguments": args}
                gathered.append((label, result))
                if lead is None:
                    lead = lead_sentence(label, result)
                shown = [ln[:300] for ln in result.splitlines()[1:9]] or result.splitlines()[:1]
                head = result.splitlines()[0][:160] if result else ""
                tool_log.append(
                    {
                        "tool": step.tool,
                        "arguments": args,
                        "summary": head,
                        "lines": shown,
                        "cites": found,
                    }
                )
                yield {
                    "type": "tool_result",
                    "tool": step.tool,
                    "summary": head,
                    "lines": shown,
                    "cites": found,
                }

            if lead:
                # What the lookup found, in the lookup's own words, goes first and is not the
                # model's to rephrase; the model only adds detail after it.
                answer.append(lead + " ")
                yield {"type": "token", "text": lead + " "}

            prompt = render_prompt(
                TASK_PROMPT_ANSWER,
                VERSIONS["answer"],
                summary=summary,
                history=history,
                question=user_text,
                evidence=self._evidence_text(gathered),
                today=datetime.now(UTC).astimezone(self._tz).strftime("%A %d %B %Y"),
                has_evidence=bool(gathered),
                lead=lead,
            )
            stream = await self._gw.chat(TASK, [{"role": "user", "content": prompt}], stream=True)
            held = (
                ""  # the first words, kept back until we know the model is not repeating the lead
            )
            checking = bool(lead)
            async for chunk in stream:
                if not chunk.delta:
                    continue
                if checking:
                    held += chunk.delta
                    if len(held) < len(lead or "") + 2:
                        continue
                    checking = False
                    delta = strip_repeat(held, lead or "")
                else:
                    delta = chunk.delta
                if delta:
                    answer.append(delta)
                    yield {"type": "token", "text": delta}
            if checking and held:
                delta = strip_repeat(held, lead or "")
                if delta:
                    answer.append(delta)
                    yield {"type": "token", "text": delta}
        except LLMError as exc:
            status = "failed"
            log.warning("assistant_answer_failed", error=str(exc))
            yield {
                "type": "error",
                "message": "The assistant's language model is not available right now. "
                "Try again in a moment.",
            }
        except (asyncio.CancelledError, GeneratorExit):
            status = "stopped"
            raise
        finally:
            text = "".join(answer).strip()
            valid, unknown = evidence.resolve(text)
            citations = [c.as_json() for c in valid]
            consulted = False
            if not citations and len(evidence):
                # The model wrote no tag that resolves. The evidence is still what the answer
                # rests on, so show it — but as "consulted", never as the model's own citation.
                citations = [{**c.as_json(), "consulted": True} for c in evidence.all()[:6]]
                consulted = True
            assistant_turns_total.labels(outcome=status).inc()
            if status != "failed" or text:
                message_id = await asyncio.shield(
                    self._store.add(
                        session_id,
                        "assistant",
                        text or "(stopped before any answer)",
                        citations=citations,
                        tools=tool_log,
                        status=status,
                    )
                )
                self._schedule_summary(session_id)

        if status == "complete":
            yield {
                "type": "citation",
                "citations": citations,
                "unknown": unknown,
                "consulted": consulted,
            }
            yield {"type": "done", "message_id": str(message_id)}

    # --- steps ---------------------------------------------------------------------------

    async def _plan(
        self,
        *,
        question: str,
        now: str,
        summary: str | None,
        history: str,
        gathered: list[tuple[str, str]],
    ) -> AgentStep:
        prompt = render_prompt(
            "assistant_agent",
            VERSIONS["agent"],
            now=now,
            tz=str(self._tz),
            cameras=", ".join(self._cameras) or "unknown",
            summary=summary,
            history=history,
            question=question,
            tools=tool_catalogue(),
            evidence=self._evidence_text(gathered),
            max_calls=MAX_CALLS,
        )
        result = await self._gw.chat(
            TASK, [{"role": "user", "content": prompt}], response_model=AgentStep
        )
        step = result.parsed
        assert isinstance(step, AgentStep)  # noqa: S101 - validated by the gateway
        return step

    async def _call(
        self, step: AgentStep, ctx: ToolContext, seen: set[str]
    ) -> tuple[str, dict[str, Any], str] | None:
        name = (step.tool or "").strip()
        tool = TOOLS.get(name)
        key = f"{name}:{json.dumps(step.arguments, sort_keys=True, default=str)}"
        if tool is None:
            return (
                f"{name or '(no tool)'}",
                step.arguments,
                f"error: there is no tool called {name!r}",
            )
        if key in seen:
            return None  # the model repeated itself: stop looping and answer
        seen.add(key)
        try:
            args = tool.args.model_validate(step.arguments)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()
            )
            return name, step.arguments, f"error: bad arguments ({problems[:300]})"
        try:
            result = await tool.run(ctx, args)
        except Exception as exc:  # a failing tool is information for the model, not a crash
            log.warning("assistant_tool_failed", tool=name, error=str(exc))
            return name, step.arguments, f"error: {name} failed ({type(exc).__name__})"
        return name, args.model_dump(mode="json", exclude_none=True), result[:RESULT_CHARS]

    @staticmethod
    def _evidence_text(gathered: list[tuple[str, str]]) -> str:
        if not gathered:
            return "(nothing yet)"
        out, used = [], 0
        for label, result in gathered:
            block = f"Result of {label}:\n{result}"
            if used + len(block) > EVIDENCE_CHARS:
                block = block[: max(0, EVIDENCE_CHARS - used)]
            out.append(block)
            used += len(block)
        return "\n\n".join(out)

    # --- memory --------------------------------------------------------------------------

    async def _summary(self, session_id: uuid.UUID) -> str | None:
        from vms_db.models import ChatSession

        async with self._store._sessions() as s:  # noqa: SLF001 - same package
            row = await s.get(ChatSession, session_id)
        return row.summary if row else None

    def _schedule_summary(self, session_id: uuid.UUID) -> None:
        task = asyncio.create_task(self._update_summary(session_id), name="chat-summary")
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _update_summary(self, session_id: uuid.UUID) -> None:
        """Fold the messages that fell out of the verbatim window into the rolling summary."""
        from vms_db.models import ChatSession

        try:
            messages = await self._store.messages(session_id)
            older, _recent = split_history(messages)
            async with self._store._sessions() as s:  # noqa: SLF001
                row = await s.get(ChatSession, session_id)
            if row is None or len(older) <= row.summarized_count:
                return
            fresh = older[row.summarized_count :]
            prompt = render_prompt(
                "assistant_summary",
                VERSIONS["summary"],
                summary=row.summary,
                messages=render_history(fresh, per_message=400),
            )
            result = await self._gw.chat(TASK, [{"role": "user", "content": prompt}])
            await self._store.set_summary(session_id, result.text.strip()[:1200], len(older))
        except Exception as exc:  # the summary is an optimisation; the window still holds
            log.warning("assistant_summary_failed", error=str(exc))


TASK_PROMPT_ANSWER = "assistant_answer"

__all__ = ["Assistant", "AgentStep", "Turn"]
