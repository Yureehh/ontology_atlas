from __future__ import annotations

from pathlib import Path

from company_ontology_agent.graph.cypher import CONSTRAINTS, EXPLORE_QUERIES


def write_bootstrap_files(project_root: Path) -> None:
    graph_dir = project_root / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)
    (graph_dir / "constraints.cypher").write_text(CONSTRAINTS, encoding="utf-8")
    (graph_dir / "explore.cypher").write_text(EXPLORE_QUERIES, encoding="utf-8")
