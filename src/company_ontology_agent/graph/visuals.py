from __future__ import annotations

from dataclasses import dataclass

from company_ontology_agent.graph.models import ExtractedGraph


@dataclass(frozen=True)
class VisualGraphSummary:
    entity_count: int
    relationship_count: int
    top_relationships: list[tuple[str, int]]

    @property
    def is_usable(self) -> bool:
        return self.entity_count > 0 and self.relationship_count > 0


def summarize_visual_graph(graph: ExtractedGraph) -> VisualGraphSummary:
    entity_ids = {entity.id for entity in graph.entities}
    predicate_counts: dict[str, int] = {}
    for assertion in graph.assertions:
        if assertion.subject_id not in entity_ids or assertion.object_id not in entity_ids:
            continue
        predicate_counts[assertion.predicate] = predicate_counts.get(assertion.predicate, 0) + 1
    top_relationships = sorted(
        predicate_counts.items(),
        key=lambda item: (-item[1], item[0]),
    )
    return VisualGraphSummary(
        entity_count=len(entity_ids),
        relationship_count=sum(predicate_counts.values()),
        top_relationships=top_relationships[:10],
    )
