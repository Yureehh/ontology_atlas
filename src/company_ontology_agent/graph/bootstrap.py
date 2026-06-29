from __future__ import annotations

from pathlib import Path

from company_ontology_agent.graph.cypher import CONSTRAINTS, EXPLORE_QUERIES


def write_bootstrap_files(project_root: Path) -> None:
    graph_dir = project_root / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)
    (graph_dir / "constraints.cypher").write_text(CONSTRAINTS, encoding="utf-8")
    (graph_dir / "bootstrap.cypher").write_text(CONSTRAINTS, encoding="utf-8")
    (graph_dir / "explore.cypher").write_text(EXPLORE_QUERIES, encoding="utf-8")
    (project_root / "NEO4J_EXPLORE_GUIDE.md").write_text(
        "# Neo4j Explore Guide\n\n"
        "Use `graph/explore.cypher` for the manager demo queries.\n\n"
        "Neo4j Explore can look empty if you click `Project`, `Source`, or `SourceSpan` "
        "labels directly. Those are provenance nodes. For the real demo graph, paste "
        "query 1 from `graph/explore.cypher`.\n\n"
        "Recommended captions:\n\n"
        "- `DemoNode`, `System`, `Module`, `Technology`, `File`, `Class`, `Function`, "
        "`APIEndpoint`, `DataModel`, `Database`, `DataStore`: `caption`\n"
        "- `DemoProject`, `Project`: `caption`\n"
        "- relationships: `caption`\n"
        "- `System`, `Module`, `Technology`, `File`, `Class`, `Function`, "
        "`APIEndpoint`, `DataModel`, `Database`, `DataStore`: `name`\n"
        "- `Assertion`: `predicate`\n"
        "- `Source`: `title`\n"
        "- `Project`: `slug`\n\n"
        "No-query Explore path: click the `DemoNode` label/category, or click "
        "`DemoProject` and expand `HAS_ENTITY`. For the cleanest manager scene, paste "
        "query 1 from `graph/explore.cypher`:\n\n"
        "```cypher\n"
        "MATCH p=(a:DemoNode)-[r]->(b:DemoNode)\n"
        "WHERE NOT a:Source AND NOT b:Source\n"
        "  AND NOT a:SourceSpan AND NOT b:SourceSpan\n"
        "  AND NOT a:Assertion AND NOT b:Assertion\n"
        "  AND NOT a:GraphifyNode AND NOT b:GraphifyNode\n"
        "  AND NOT a:GraphifyEdge AND NOT b:GraphifyEdge\n"
        "RETURN p\n"
        "LIMIT 200;\n"
        "```\n",
        encoding="utf-8",
    )
    (graph_dir / "migrations").mkdir(exist_ok=True)
