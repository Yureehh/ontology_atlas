from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from company_ontology_agent.config.project_config import default_config
from company_ontology_agent.extraction.code_map import write_code_map
from company_ontology_agent.extraction.graphify_artifacts import parse_graphify_graph
from company_ontology_agent.graph.cypher import EXPLORE_QUERIES
from company_ontology_agent.graph.models import (
    Assertion,
    Entity,
    EntityType,
    ExtractedGraph,
    Source,
    SourceSpan,
)
from company_ontology_agent.graph.repository import Neo4jGraphRepository
from company_ontology_agent.portal.builder import PortalBuilder
from company_ontology_agent.wiki.relationships import key_relationship_sections
from company_ontology_agent.workflows.projection import build_curated_projection


def test_curated_projection_creates_explorable_architecture(tmp_path: Path) -> None:
    project_root = tmp_path
    raw = project_root / "data/raw/backend/app"
    raw.mkdir(parents=True)
    (raw / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "from sqlalchemy import Column\n"
        "app = FastAPI()\n"
        "@app.get('/reports')\n"
        "def list_reports():\n"
        "    return []\n"
        "class ReportModel:\n"
        "    pass\n",
        encoding="utf-8",
    )
    (project_root / "data/raw/frontend/src").mkdir(parents=True)
    (project_root / "data/raw/frontend/src/App.tsx").write_text(
        "import React from 'react';\n",
        encoding="utf-8",
    )
    config = default_config("slidesmith-poc")

    graph = build_curated_projection(project_root, config)

    entity_types = {entity.type for entity in graph.entities}
    predicates = {assertion.predicate for assertion in graph.assertions}
    names = {entity.name for entity in graph.entities}

    assert EntityType.module in entity_types
    assert EntityType.api_endpoint in entity_types
    assert EntityType.data_model in entity_types
    assert {"Backend", "Frontend", "Data Layer", "Deployment"}.issubset(names)
    assert {"contains", "exposes", "defines", "uses", "writes_to"}.issubset(predicates)


def test_curated_projection_does_not_treat_generic_vector_as_pgvector(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "data/raw/backend"
    raw.mkdir(parents=True)
    (raw / "features.py").write_text(
        "class FeatureVector:\n    pass\n",
        encoding="utf-8",
    )
    config = default_config("vector-poc")

    graph = build_curated_projection(tmp_path, config)

    assert "pgvector" not in {entity.name for entity in graph.entities}


def test_hardcoded_projection_is_disabled_by_default() -> None:
    config = default_config("default-poc")

    assert config.extraction.ontology_projection_enabled is False


def test_portal_build_writes_graph_and_index(tmp_path: Path) -> None:
    graph = _small_graph()
    graphify_dir = tmp_path / "graphify-out"
    graphify_dir.mkdir()
    for name in ["graph.html", "graph.raw.html", "GRAPH_TREE.html", "GRAPH_REPORT.md"]:
        (graphify_dir / name).write_text(name, encoding="utf-8")

    files = PortalBuilder().build(
        graph,
        tmp_path,
        tmp_path / "portal",
        display_name="Ontology Atlas Oracle Bets Ontology",
    )

    names = {path.name for path in files}
    assert {
        "index.html",
        "ask.html",
        "explore.html",
        "intelligence.html",
        "graph.json",
    } <= names
    assert not (tmp_path / "portal/trust.html").exists()
    # Legacy single-page artifact must be gone.
    assert not (tmp_path / "portal/repo-ontology.html").exists()

    index_html = (tmp_path / "portal/index.html").read_text(encoding="utf-8")
    ask_html = (tmp_path / "portal/ask.html").read_text(encoding="utf-8")
    explore_html = (tmp_path / "portal/explore.html").read_text(encoding="utf-8")
    intel_html = (tmp_path / "portal/intelligence.html").read_text(encoding="utf-8")
    data = json.loads((tmp_path / "portal/graph.json").read_text(encoding="utf-8"))

    # index.html is a lightweight redirect to the answer-first experience.
    assert "Ontology Portal" in index_html
    assert "url=ask.html" in index_html
    assert "const rawData" not in index_html

    def bootstrap(html: str) -> dict:
        return json.loads(re.search(r'id="portal-data">(.*?)</script>', html, re.S).group(1))

    ask_data = bootstrap(ask_html)
    explore_data = bootstrap(explore_html)
    intel_data = bootstrap(intel_html)
    assert ask_data["page"] == "ask"
    assert explore_data["page"] == "explore" and explore_data["kind"] == "repo"
    assert intel_data["page"] == "intelligence"
    # Shared shell + tabs render on the real pages.
    assert "Oracle Bets" in explore_html  # public_project_name strips "Ontology Atlas"
    assert 'href="ask.html"' in explore_html and 'href="changes.html"' in explore_html
    assert 'href="trust.html"' not in explore_html
    summary_names = {node["name"] for node in explore_data["nodes"]}
    assert {"Blue Team", "Match 1"} <= summary_names
    assert len(explore_data["nodes"]) <= 30 + 2
    assert all(node["type"] != "BusinessEntity" for node in explore_data["nodes"])

    # The full graph.json keeps everything, flat, with rich link metadata.
    assert len(data["nodes"]) == 5 and len(data["links"]) == 2
    assert {"confidence_tier", "evidence_level", "key_relationship", "graph_kind"}.issubset(
        data["links"][0]
    )
    graph_kinds = {node["name"]: node["graph_kind"] for node in data["nodes"]}
    assert graph_kinds["Backend"] == "repo" and graph_kinds["Blue Team"] == "data"
    visual_types = {node["name"]: node["visual_type"] for node in data["nodes"]}
    assert visual_types["predict.py"] == "File" and visual_types["Blue Team"] == "Team"

    # The curated code/docs map is available only as a clearly scoped diagnostic.
    assert {a["url"] for a in explore_data["artifacts"]} == {
        "../graphify-out/graph.html",
        "../graphify-out/graph.raw.html",
        "../graphify-out/GRAPH_TREE.html",
        "../graphify-out/GRAPH_REPORT.md",
    }
    raw_map = next(
        artifact
        for artifact in explore_data["artifacts"]
        if artifact["url"].endswith("graph.html")
    )
    assert raw_map["label"] == "Code & docs map"
    assert "description" not in raw_map


def test_key_relationship_ranking_promotes_api_data_and_model_edges() -> None:
    graph = ExtractedGraph(
        project_slug="ranking-poc",
        entities=[
            Entity(id="file", type=EntityType.file, name="features.py", normalized_name="features"),
            Entity(
                id="fn1",
                type=EntityType.function,
                name="_rolling_mean",
                normalized_name="rolling mean",
            ),
            Entity(
                id="fn2",
                type=EntityType.function,
                name="_safe_divide",
                normalized_name="safe divide",
            ),
            Entity(
                id="api",
                type=EntityType.api_endpoint,
                name="GET /predict",
                normalized_name="get predict",
            ),
            Entity(
                id="model",
                type=EntityType.data_model,
                name="Prediction",
                normalized_name="prediction",
            ),
            Entity(
                id="match",
                type=EntityType.business_entity,
                name="match-1",
                normalized_name="match 1",
                metadata={"mapped_type": "Match"},
            ),
            Entity(
                id="prediction",
                type=EntityType.business_entity,
                name="prediction-1",
                normalized_name="prediction 1",
                metadata={"mapped_type": "Prediction"},
            ),
        ],
        assertions=[
            _assertion("c1", "contains", "file", "fn1", "features.py"),
            _assertion("c2", "contains", "file", "fn2", "features.py"),
            _assertion("api", "exposes", "file", "api", "routes.py"),
            _assertion("data", "writes_to", "api", "model", "routes.py"),
            _assertion(
                "pred",
                "prediction_for_match",
                "prediction",
                "match",
                "predictions.parquet",
            ),
        ],
    )

    sections = key_relationship_sections(graph, per_section=4)
    chosen = {assertion.id for items in sections.values() for assertion, _, _ in items}

    assert {"api", "data", "pred"}.issubset(chosen)
    assert "c1" not in chosen or "c2" not in chosen


def test_explore_query_defaults_to_curated_graph() -> None:
    first_query = EXPLORE_QUERIES.split("// 2.", maxsplit=1)[0]

    assert "// 1. Curated explorable graph" in first_query
    assert "MATCH p=(a:DemoNode)-[r]->(b:DemoNode)" in first_query
    assert "NOT a:Source" in first_query
    assert "NOT a:SourceSpan" in first_query
    assert "NOT a:Assertion" in first_query
    assert "NOT a:GraphifyNode" in first_query
    assert "NOT a:GraphifyEdge" in first_query


def test_graphify_parser_preserves_rich_metadata(tmp_path: Path) -> None:
    graph_json = tmp_path / "graph.json"
    graph_json.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "id": "api-1",
                        "label": "GET /reports",
                        "type": "endpoint",
                        "file": "backend/app/main.py",
                        "community": "Backend API",
                        "degree": 4,
                    },
                    {
                        "id": "model-1",
                        "label": "ReportModel",
                        "type": "model",
                        "file": "backend/app/main.py",
                        "community": "Data",
                    },
                    {
                        "id": "fn-1",
                        "label": "predict()",
                        "_origin": "ast",
                        "file_type": "code",
                        "source_file": "packages/lol_bets/predictor.py",
                    },
                    {
                        "id": "file-1",
                        "label": "predictor.py",
                        "_origin": "ast",
                        "file_type": "code",
                        "source_file": "packages/lol_bets/predictor.py",
                    },
                ],
                "edges": [
                    {
                        "id": "edge-1",
                        "source": "api-1",
                        "target": "model-1",
                        "relation": "uses",
                        "context": "Endpoint serializes reports.",
                        "confidence": 0.87,
                        "community": "Backend API",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    graph = parse_graphify_graph(graph_json, "slidesmith-poc")

    assert graph.entities[0].type == EntityType.api_endpoint
    assert graph.entities[0].graphify_id == "api-1"
    assert graph.entities[0].source_path == "backend/app/main.py"
    assert graph.entities[0].community == "Backend API"
    by_id = {entity.graphify_id: entity for entity in graph.entities}
    assert by_id["fn-1"].type == EntityType.function
    assert by_id["fn-1"].source_path == "packages/lol_bets/predictor.py"
    assert by_id["fn-1"].extraction_source == "graphify_ast"
    assert by_id["file-1"].type == EntityType.file
    assert graph.assertions[0].graphify_id == "edge-1"
    assert graph.assertions[0].predicate == "uses"
    assert graph.assertions[0].evidence_text == "Endpoint serializes reports."


def test_code_map_is_bounded_and_preserves_raw_graphify_html(tmp_path: Path) -> None:
    graph = ExtractedGraph(project_slug="portable")
    for community in range(55):
        for member in range(3):
            entity_id = f"c{community}-{member}"
            graph.entities.append(
                Entity(
                    id=entity_id,
                    type=EntityType.module,
                    name=f"VeryLongGeneratedRepositoryComponent{community}_{member}",
                    normalized_name=entity_id,
                    community=f"Community {community} with an excessively long generated title",
                    source_path=f"packages/package-{community}/src/module-{member}.py",
                )
            )
    graphify_out = tmp_path / "graphify-out"
    graphify_out.mkdir()
    (graphify_out / "graph.html").write_text("<html>raw graphify</html>", encoding="utf-8")

    write_code_map(graph, graphify_out)

    html = (graphify_out / "graph.html").read_text(encoding="utf-8")
    assert 'data-ontology-atlas-code-map="true"' in html
    assert "Code &amp; docs map" in html
    assert html.count('class="community-card"') <= 40
    assert (graphify_out / "graph.raw.html").read_text(encoding="utf-8") == (
        "<html>raw graphify</html>"
    )


def test_neo4j_repository_writes_visual_relationships() -> None:
    client = FakeNeo4jClient()
    repository = Neo4jGraphRepository(client)

    repository.upsert_graph(_small_graph())

    statements = "\n".join(statement for statement, _ in client.calls)
    assert "MERGE (p:Project:DemoProject {slug: $slug})" in statements
    assert "MERGE (e:DemoNode:Entity:Module {id: row.id})" in statements
    assert "MERGE (p)-[r:HAS_ENTITY]->(e)" in statements
    assert "MERGE (subject)-[r:USES {assertion_id: row.assertion_id}]->(object)" in statements
    assert "a.caption = row.predicate" in statements
    assertion_props = next(
        row["props"]
        for _, params in client.calls
        for row in params.get("rows", [])
        if row.get("id") == "a1"
    )
    assert "metadata_json" in assertion_props
    assert "metadata" not in assertion_props
    entity_props = next(
        row["props"]
        for _, params in client.calls
        for row in params.get("rows", [])
        if row.get("id") == "e1"
    )
    assert entity_props["caption"] == "Backend"
    assert entity_props["demo_node"] is True
    assert len(client.calls) < 20


def test_neo4j_repository_reads_only_current_graph_records() -> None:
    client = FakeNeo4jClient()

    Neo4jGraphRepository(client).read_graph("slidesmith-poc")

    statements = "\n".join(statement for statement, _ in client.calls)
    assert "[:HAS_ENTITY]->(e:Entity)" in statements
    assert "coalesce(e.stale, false) = false" in statements
    assert "coalesce(a.stale, false) = false" in statements


class FakeNeo4jClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, statement: str, parameters: dict[str, Any] | None = None) -> None:
        self.calls.append((statement, parameters or {}))

    def query(
        self, statement: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        self.calls.append((statement, parameters or {}))
        return []


def _small_graph() -> ExtractedGraph:
    return ExtractedGraph(
        project_slug="slidesmith-poc",
        sources=[
            Source(
                id="s1",
                path="backend/app/main.py",
                source_type="python",
                sha256="abc",
                title="main.py",
            )
        ],
        source_spans=[SourceSpan(id="span1", source_id="s1", text="FastAPI uses ReportModel.")],
        entities=[
            Entity(
                id="e1",
                type=EntityType.module,
                name="Backend",
                normalized_name="backend",
            ),
            Entity(
                id="e2",
                type=EntityType.technology,
                name="FastAPI",
                normalized_name="fastapi",
            ),
            Entity(
                id="e5",
                type=EntityType.concept,
                name="predict.py",
                normalized_name="predict py",
                source_path="backend/app/predict.py",
            ),
            Entity(
                id="e3",
                type=EntityType.business_entity,
                name="Blue Team",
                normalized_name="blue team",
                extraction_source="structured_connector",
                metadata={
                    "domain": "betting",
                    "dataset": "oracle_bets_matches",
                    "connector": "parquet",
                    "mapped_type": "Team",
                },
            ),
            Entity(
                id="e4",
                type=EntityType.business_entity,
                name="Match 1",
                normalized_name="match 1",
                extraction_source="structured_connector",
                metadata={
                    "domain": "betting",
                    "dataset": "oracle_bets_matches",
                    "connector": "parquet",
                    "mapped_type": "Match",
                },
            ),
        ],
        assertions=[
            Assertion(
                id="a1",
                predicate="uses",
                subject_id="e1",
                object_id="e2",
                evidence_span_id="span1",
                confidence=0.91,
                extractor="test",
                metadata={"source": "fixture"},
            ),
            Assertion(
                id="a2",
                predicate="team_played_match",
                subject_id="e3",
                object_id="e4",
                evidence_span_id="span1",
                confidence=1.0,
                extractor="structured",
                extraction_source="structured_connector",
                metadata={
                    "domain": "betting",
                    "dataset": "oracle_bets_matches",
                    "connector": "parquet",
                },
            ),
        ],
    )


def _assertion(
    assertion_id: str, predicate: str, subject_id: str, object_id: str, source_path: str
) -> Assertion:
    return Assertion(
        id=assertion_id,
        predicate=predicate,
        subject_id=subject_id,
        object_id=object_id,
        evidence_span_id="span",
        confidence=0.8,
        extractor="test",
        source_path=source_path,
        evidence_text=f"{subject_id} {predicate} {object_id}",
    )
