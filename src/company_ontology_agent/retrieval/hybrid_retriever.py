from __future__ import annotations

from pathlib import Path

from company_ontology_agent.graph.models import ExtractedGraph
from company_ontology_agent.retrieval.graph_retriever import retrieve_graph_context
from company_ontology_agent.retrieval.wiki_retriever import retrieve_wiki_context


def retrieve_hybrid_context(
    graph: ExtractedGraph, wiki_path: Path, question: str, top_k: int = 8
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    return (
        retrieve_graph_context(graph, question, top_k),
        retrieve_wiki_context(wiki_path, question, top_k),
    )
