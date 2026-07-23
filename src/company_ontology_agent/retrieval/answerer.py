from __future__ import annotations

from markdown_it import MarkdownIt
from pydantic import BaseModel, Field, computed_field

_MARKDOWN = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})


class Citation(BaseModel):
    source_path: str
    record_locator: str | None = None
    evidence: str
    evidence_level: str = "evidence_backed"
    score: float | None = None
    chunk_id: str | None = None
    source_span_ids: list[str] = Field(default_factory=list)


class AnalysisMetadata(BaseModel):
    mode: str
    operation: str
    metric: str = ""
    grouping: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    rows: list[dict[str, object]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    paths: list[dict[str, object]] = Field(default_factory=list)
    supporting_assertions: list[dict[str, object]] = Field(default_factory=list)
    supporting_chunks: list[dict[str, object]] = Field(default_factory=list)
    entities: list[dict[str, object]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    timings_ms: dict[str, float] = Field(default_factory=dict)
    analysis: AnalysisMetadata | None = None
    trace_id: str

    @computed_field(return_type=str)  # type: ignore[prop-decorator]
    @property
    def answer_html(self) -> str:
        """Safe server-rendered Markdown; raw HTML from model output stays escaped."""
        return str(_MARKDOWN.render(self.answer))
