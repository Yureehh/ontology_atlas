from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field


class EntityType(StrEnum):
    person = "Person"
    organization = "Organization"
    technology = "Technology"
    concept = "Concept"
    system = "System"
    module = "Module"
    package = "Package"
    file = "File"
    class_ = "Class"
    function = "Function"
    api_endpoint = "APIEndpoint"
    data_model = "DataModel"
    database = "Database"
    data_store = "DataStore"
    queue = "Queue"
    external_service = "ExternalService"
    deployment_unit = "DeploymentUnit"
    environment = "Environment"
    config = "Config"
    secret_ref = "SecretRef"
    workflow = "Workflow"
    user_role = "UserRole"
    decision = "Decision"
    requirement = "Requirement"
    issue = "Issue"
    task = "Task"
    business_entity = "BusinessEntity"


class AssertionStatus(StrEnum):
    candidate = "candidate"
    validated = "validated"
    rejected = "rejected"
    superseded = "superseded"
    disputed = "disputed"


class Source(BaseModel):
    id: str
    path: str
    source_type: str
    sha256: str
    title: str


class SourceSpan(BaseModel):
    id: str
    source_id: str
    start: int = 0
    end: int = 0
    text: str


class Chunk(BaseModel):
    id: str
    source_span_id: str
    text: str
    ordinal: int = 0


class Entity(BaseModel):
    id: str
    type: EntityType
    name: str
    normalized_name: str
    aliases: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)
    graphify_id: str | None = None
    source_path: str | None = None
    community: str | None = None
    extraction_source: str = "local_fallback"
    confidence_tier: str = "extracted"
    description: str | None = None
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class Assertion(BaseModel):
    id: str
    predicate: str
    subject_id: str
    object_id: str
    evidence_span_id: str
    confidence: float = Field(ge=0, le=1)
    status: AssertionStatus = AssertionStatus.candidate
    extractor: str
    extractor_version: str = "0.1.0"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    classification: str = "internal"
    graphify_id: str | None = None
    source_path: str | None = None
    community: str | None = None
    extraction_source: str = "local_fallback"
    confidence_tier: str = "extracted"
    evidence_text: str | None = None
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class ExtractedGraph(BaseModel):
    project_slug: str
    sources: list[Source] = Field(default_factory=list)
    source_spans: list[SourceSpan] = Field(default_factory=list)
    chunks: list[Chunk] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    assertions: list[Assertion] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def merge(self, other: ExtractedGraph) -> ExtractedGraph:
        return ExtractedGraph(
            project_slug=self.project_slug,
            sources=_dedupe(self.sources + other.sources),
            source_spans=_dedupe(self.source_spans + other.source_spans),
            chunks=_dedupe(self.chunks + other.chunks),
            entities=_dedupe(self.entities + other.entities),
            assertions=_dedupe(self.assertions + other.assertions),
            warnings=list(dict.fromkeys([*self.warnings, *other.warnings])),
        )


def entity_graph_kind(entity: Entity) -> str:
    """Classify an entity as part of the structured "data" graph or the "repo" graph.

    Single source of truth shared by the portal and wiki so the two layers never drift.
    """
    if (
        entity.type == EntityType.business_entity
        or entity.extraction_source == "structured_connector"
        or entity.metadata.get("connector")
    ):
        return "data"
    return "repo"


def assertion_graph_kind(assertion: Assertion, node_kind_by_id: dict[str, str]) -> str:
    """Classify an assertion; a relationship touching any data node is a data relationship."""
    if (
        assertion.extraction_source == "structured_connector"
        or assertion.metadata.get("connector")
        or node_kind_by_id.get(assertion.subject_id) == "data"
        or node_kind_by_id.get(assertion.object_id) == "data"
    ):
        return "data"
    return "repo"


class HasId(Protocol):
    id: str


def _dedupe[T: HasId](items: list[T]) -> list[T]:
    seen: set[str] = set()
    result: list[T] = []
    for item in items:
        item_id = item.id
        if item_id not in seen:
            seen.add(item_id)
            result.append(item)
    return result
