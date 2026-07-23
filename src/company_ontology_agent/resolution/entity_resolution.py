from __future__ import annotations

import re

from pydantic import BaseModel, Field

from company_ontology_agent.graph.models import Entity, ExtractedGraph
from company_ontology_agent.resolution.canonicalization import canonical_name
from company_ontology_agent.utils.display import is_opaque_entity_name
from company_ontology_agent.utils.ids import stable_id


class ResolutionResult(BaseModel):
    canonical_entity_id: str
    matched_entities: list[str] = Field(default_factory=list)
    confidence: float
    strategy: str


class EntityResolver:
    def resolve(self, graph: ExtractedGraph) -> tuple[ExtractedGraph, list[ResolutionResult]]:
        canonical: dict[tuple[str, ...], Entity] = {}
        id_map: dict[str, str] = {}
        results: list[ResolutionResult] = []

        for entity in graph.entities:
            key = _resolution_key(entity, graph.project_slug)
            canonical_id = stable_id("entity", *key)
            id_map[entity.id] = canonical_id
            existing = canonical.get(key)
            if existing is None:
                canonical[key] = entity.model_copy(
                    update={"id": canonical_id, "metadata": _provenance_metadata(entity)}
                )
                results.append(
                    ResolutionResult(
                        canonical_entity_id=canonical_id,
                        matched_entities=[entity.id],
                        confidence=1.0,
                        strategy="normalized_name",
                    )
                )
            else:
                merged_spans = sorted(set(existing.source_span_ids + entity.source_span_ids))
                preferred, alternate = _prefer_display_name(existing, entity)
                merged_aliases = sorted(
                    set(existing.aliases + entity.aliases + [alternate.name]) - {preferred.name}
                )
                canonical[key] = existing.model_copy(
                    update={
                        "name": preferred.name,
                        "normalized_name": canonical_name(preferred.name),
                        "description": preferred.description or alternate.description,
                        "source_path": preferred.source_path or alternate.source_path,
                        "source_span_ids": merged_spans,
                        "aliases": merged_aliases,
                        "metadata": _provenance_metadata(preferred, alternate),
                    }
                )
                results.append(
                    ResolutionResult(
                        canonical_entity_id=existing.id,
                        matched_entities=[existing.id, entity.id],
                        confidence=0.91,
                        strategy="normalized_name",
                    )
                )

        assertions = [
            assertion.model_copy(
                update={
                    "id": stable_id("assertion", graph.project_slug, assertion.id),
                    "subject_id": id_map.get(assertion.subject_id, assertion.subject_id),
                    "object_id": id_map.get(assertion.object_id, assertion.object_id),
                }
            )
            for assertion in graph.assertions
        ]
        resolved_graph = graph.model_copy(
            update={"entities": list(canonical.values()), "assertions": assertions}
        )
        return (
            resolved_graph,
            results,
        )


def _resolution_key(entity: Entity, project_slug: str) -> tuple[str, ...]:
    metadata = entity.metadata
    if entity.extraction_source == "structured_connector" and all(
        metadata.get(field) for field in ("domain", "mapped_type", "record_key")
    ):
        return (
            project_slug,
            "structured",
            str(metadata["domain"]),
            str(metadata["mapped_type"]),
            str(metadata["record_key"]),
        )
    return (
        project_slug,
        "named",
        canonical_name(entity.normalized_name or entity.name),
        entity.type.value,
    )


def _prefer_display_name(first: Entity, second: Entity) -> tuple[Entity, Entity]:
    if _display_name_score(second.name) > _display_name_score(first.name):
        return second, first
    return first, second


def _provenance_metadata(preferred: Entity, alternate: Entity | None = None) -> dict[str, object]:
    entities = [entity for entity in (preferred, alternate) if entity is not None]
    metadata: dict[str, object] = {}
    for entity in reversed(entities):
        metadata.update(entity.metadata)
    datasets = {
        str(dataset)
        for entity in entities
        for dataset in (
            _as_strings(entity.metadata.get("datasets"))
            + ([entity.metadata.get("dataset")] if entity.metadata.get("dataset") else [])
        )
    }
    source_paths = {
        str(path)
        for entity in entities
        for path in (
            _as_strings(entity.metadata.get("source_paths"))
            + ([entity.source_path] if entity.source_path else [])
        )
    }
    dataset_sources: dict[str, set[str]] = {}
    for entity in entities:
        existing_sources = entity.metadata.get("dataset_sources")
        if isinstance(existing_sources, dict):
            for dataset, paths in existing_sources.items():
                dataset_sources.setdefault(str(dataset), set()).update(_as_strings(paths))
        dataset_value = entity.metadata.get("dataset")
        if dataset_value and entity.source_path:
            dataset_sources.setdefault(str(dataset_value), set()).add(entity.source_path)
    if datasets:
        metadata["datasets"] = sorted(datasets)
    if source_paths:
        metadata["source_paths"] = sorted(source_paths)
    if dataset_sources:
        metadata["dataset_sources"] = {
            dataset: sorted(paths) for dataset, paths in sorted(dataset_sources.items())
        }
    return metadata


def _as_strings(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item]
    return [str(value)] if value else []


def _display_name_score(name: str) -> tuple[int, int]:
    stripped = name.strip()
    opaque = is_opaque_entity_name(stripped)
    has_words = bool(re.search(r"[A-Za-z]{2,}[ -][A-Za-z]{2,}", stripped))
    return (0 if opaque else 2 if has_words else 1, -len(stripped))
