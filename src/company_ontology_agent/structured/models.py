from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class StructuredRecord(BaseModel):
    source: str
    row_number: int
    values: dict[str, Any]


class StructuredDataset(BaseModel):
    name: str
    domain: str
    connector: str
    records_by_source: dict[str, list[StructuredRecord]] = Field(default_factory=dict)


class EntityMapping(BaseModel):
    source: str
    type: str
    key: str | list[str]
    name: str
    properties: list[str] = Field(default_factory=list)
    redact: list[str] = Field(default_factory=list)


class RelationshipMapping(BaseModel):
    type: str
    from_entity: str
    from_key: str | list[str]
    to_entity: str
    to_key: str


class DatasetMapping(BaseModel):
    entities: dict[str, EntityMapping]
    relationships: list[RelationshipMapping] = Field(default_factory=list)


class DatasetInspection(BaseModel):
    name: str
    domain: str
    connector: str
    sources: dict[str, int]
    columns: dict[str, list[str]] = Field(default_factory=dict)


PruneMode = Literal["none", "stale", "delete"]
