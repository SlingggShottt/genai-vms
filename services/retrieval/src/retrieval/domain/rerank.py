"""Pieces of the reasoning rerank that need no I/O: the excerpt a candidate is shown to the
model as, and how the model's score is blended with the fused one."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class RerankItem(BaseModel):
    id: str
    score: float = Field(ge=0, le=1)
    trace: str = ""
    missing: list[str] = Field(default_factory=list)

    @field_validator("score", mode="before")
    @classmethod
    def _accept_percent_scale(cls, v: object) -> object:
        # Small models like to answer 0-10 or 0-100 whatever the prompt says.
        if isinstance(v, int | float):
            if v > 10:
                return v / 100
            if v > 1:
                return v / 10
        return v

    @field_validator("trace", mode="after")
    @classmethod
    def _cap_trace(cls, v: str) -> str:
        words = v.split()
        return " ".join(words[:60])


class RerankBatch(BaseModel):
    results: list[RerankItem]


def blend(fused: float, reasoning: float | None, weight: float) -> float:
    """Final ranking score: the fused score alone when the model gave none."""
    if reasoning is None:
        return fused
    return round((1 - weight) * fused + weight * reasoning, 4)


def format_candidate(index_id: str, *, camera: str, when: str, lines: list[str]) -> str:
    body = "\n".join(f"  - {line}" for line in lines) or "  - (no detections in this window)"
    return f"[{index_id}] camera {camera}, {when}\n{body}"
