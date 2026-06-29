from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from company_ontology_agent.graph.models import EntityType


class ExtractedEntityPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: EntityType = EntityType.concept
    aliases: list[str] = Field(default_factory=list)
    evidence: str | None = None


class ExtractedAssertionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    predicate: str
    object: str
    confidence: float = Field(default=0.7, ge=0, le=1)
    evidence: str | None = None


class StructuredExtractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entities: list[ExtractedEntityPayload] = Field(default_factory=list)
    assertions: list[ExtractedAssertionPayload] = Field(default_factory=list)
