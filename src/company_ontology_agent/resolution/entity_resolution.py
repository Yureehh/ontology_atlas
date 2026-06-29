from __future__ import annotations

from pydantic import BaseModel, Field

from company_ontology_agent.graph.models import Entity, ExtractedGraph
from company_ontology_agent.resolution.canonicalization import canonical_name
from company_ontology_agent.utils.ids import stable_id


class ResolutionResult(BaseModel):
    canonical_entity_id: str
    matched_entities: list[str] = Field(default_factory=list)
    confidence: float
    strategy: str


class EntityResolver:
    def resolve(self, graph: ExtractedGraph) -> tuple[ExtractedGraph, list[ResolutionResult]]:
        canonical: dict[tuple[str, str], Entity] = {}
        id_map: dict[str, str] = {}
        results: list[ResolutionResult] = []

        for entity in graph.entities:
            key = (canonical_name(entity.normalized_name or entity.name), entity.type.value)
            canonical_id = stable_id("entity", key[0], key[1])
            id_map[entity.id] = canonical_id
            existing = canonical.get(key)
            if existing is None:
                canonical[key] = entity.model_copy(
                    update={"id": canonical_id, "normalized_name": key[0]}
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
                merged_aliases = sorted(set(existing.aliases + entity.aliases + [entity.name]))
                canonical[key] = existing.model_copy(
                    update={"source_span_ids": merged_spans, "aliases": merged_aliases}
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
