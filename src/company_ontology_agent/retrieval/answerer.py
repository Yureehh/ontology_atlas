from __future__ import annotations

from pydantic import BaseModel, Field


class QueryResponse(BaseModel):
    answer: str
    supporting_assertions: list[dict[str, object]] = Field(default_factory=list)
    supporting_chunks: list[dict[str, object]] = Field(default_factory=list)
    entities: list[dict[str, object]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    trace_id: str


def answer_from_context(
    question: str,
    entities: list[dict[str, str]],
    wiki_chunks: list[dict[str, str]],
    trace_id: str,
) -> QueryResponse:
    if not entities and not wiki_chunks:
        return QueryResponse(
            answer="I do not have enough project evidence to answer that question.",
            warnings=["No matching graph or wiki context found."],
            trace_id=trace_id,
        )
    names = ", ".join(entity["name"] for entity in entities) or "the retrieved wiki context"
    return QueryResponse(
        answer=f"Based on available project evidence, the relevant context is: {names}.",
        supporting_chunks=wiki_chunks,
        entities=entities,
        trace_id=trace_id,
    )
