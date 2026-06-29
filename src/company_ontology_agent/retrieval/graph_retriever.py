from __future__ import annotations

from company_ontology_agent.graph.models import ExtractedGraph


def retrieve_graph_context(
    graph: ExtractedGraph, question: str, top_k: int = 8
) -> list[dict[str, str]]:
    question_lower = question.lower()
    matches = [
        {"id": entity.id, "name": entity.name, "type": entity.type.value}
        for entity in graph.entities
        if entity.name.lower() in question_lower or question_lower in entity.name.lower()
    ]
    return matches[:top_k]
