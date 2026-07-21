from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import company_ontology_agent.extraction.graphify_adapter as graphify_adapter
from company_ontology_agent.config.templates import scaffold_project
from company_ontology_agent.extraction.graphify_adapter import (
    GraphifyCommand,
    GraphifyExtractor,
    _graphify_visible_input,
    apply_community_names,
    parse_graphify_graph,
)
from company_ontology_agent.extraction.llm_structured_extractor import LLMStructuredExtractor
from company_ontology_agent.extraction.openai_provider import openai_strict_json_schema
from company_ontology_agent.extraction.provider import LLMProvider
from company_ontology_agent.extraction.schemas import StructuredExtractionPayload
from company_ontology_agent.graph.neo4j_client import Neo4jClient, Neo4jConnection
from company_ontology_agent.graph.repository import Neo4jGraphRepository
from company_ontology_agent.ontology.validator import OntologyValidator
from company_ontology_agent.wiki.exporter import WikiExporter


class FakeProvider(LLMProvider):
    def __init__(self, payload: StructuredExtractionPayload) -> None:
        self.payload = payload

    def extract(self, text: str) -> StructuredExtractionPayload:
        return self.payload


def test_graphify_command_uses_documented_cli_shape(tmp_path: Path) -> None:
    command = GraphifyCommand(
        executable="graphify",
        input_path=tmp_path / "data/raw",
        output_path=tmp_path / "graphify-out",
        backend="openai",
        mode="deep",
        model="gpt-test",
        no_viz=True,
    )

    argv = command.argv()

    assert Path(argv[0]).name == "graphify"
    assert argv[1:] == [
        "extract",
        str(tmp_path / "data/raw"),
        "--backend",
        "openai",
        "--mode",
        "deep",
        "--out",
        str((tmp_path / "graphify-out").parent),
        "--model",
        "gpt-test",
        "--no-viz",
    ]


def test_graphify_visible_input_mirrors_hidden_project_paths(tmp_path: Path) -> None:
    hidden_raw = tmp_path / ".ontology-agent" / "data" / "raw"
    hidden_raw.mkdir(parents=True)
    (hidden_raw / "main.py").write_text("print('ok')\n", encoding="utf-8")

    with _graphify_visible_input(hidden_raw) as visible:
        assert visible != hidden_raw.resolve()
        assert ".ontology-agent" not in visible.parts
        assert (visible / "main.py").exists()

    assert not visible.exists()


def test_graphify_graph_json_converts_to_internal_graph() -> None:
    graph = parse_graphify_graph(Path("tests/fixtures/graphify/graph.json"), "acme-poc")

    assert len(graph.sources) == 1
    assert len(graph.source_spans) == 2
    assert len(graph.entities) == 3
    assert len(graph.assertions) == 2
    assert {assertion.extractor for assertion in graph.assertions} == {"graphify"}


def test_graphify_community_labels_are_applied_from_sidecar(tmp_path: Path) -> None:
    graph_json = tmp_path / "graph.json"
    graph_json.write_text(
        json.dumps(
            {
                "nodes": [
                    {"id": "api", "label": "GET /predict", "community": 7},
                    {"id": "model", "label": "PredictionModel", "community": 7},
                ],
                "links": [
                    {
                        "source": "api",
                        "target": "model",
                        "relation": "uses",
                        "community": 7,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / ".graphify_labels.json").write_text(
        json.dumps({"communities": {"7": "Prediction API"}}),
        encoding="utf-8",
    )

    graph = apply_community_names(parse_graphify_graph(graph_json, "acme-poc"), tmp_path)

    assert {entity.community for entity in graph.entities} == {"Prediction API"}
    assert graph.assertions[0].community == "Prediction API"
    assert graph.entities[0].metadata["community_id"] == "7"


def test_graphify_community_names_are_inferred_without_sidecar(tmp_path: Path) -> None:
    graph_json = tmp_path / "graph.json"
    graph_json.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "id": "feature",
                        "label": "FeatureGenerator",
                        "source_file": "packages/lol/features_generator.py",
                        "community": 3,
                    },
                    {
                        "id": "rolling",
                        "label": "RollingMeanFeature",
                        "source_file": "packages/lol/features_generator.py",
                        "community": 3,
                    },
                ],
                "links": [],
            }
        ),
        encoding="utf-8",
    )

    graph = apply_community_names(parse_graphify_graph(graph_json, "acme-poc"), tmp_path)

    assert "Community 3" not in {entity.community for entity in graph.entities}
    assert all(entity.community for entity in graph.entities)


def test_graphify_failure_uses_existing_graph_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "graphify-out"
    output.mkdir()
    shutil.copy(Path("tests/fixtures/graphify/graph.json"), output / "graph.json")
    extractor = GraphifyExtractor(output, executable="graphify")

    monkeypatch.setattr(graphify_adapter, "resolve_graphify_executable", lambda _: "graphify")

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        progress: graphify_adapter.ProgressReporter | None,
        heartbeat_seconds: int,
        completion_file: Path | None = None,
        completion_grace_seconds: int = 90,
        max_runtime_seconds: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "timeout")

    monkeypatch.setattr(graphify_adapter, "_run_with_heartbeat", fake_run)

    result = extractor.run(tmp_path / "raw", "acme-poc")

    assert result.exit_code == 1
    assert result.graph_json_path == output / "graph.json"
    assert len(result.graph.entities) == 3
    assert len(result.graph.assertions) == 2
    assert result.graph.warnings == ["Graphify execution failed; see graphify-out/GRAPH_REPORT.md."]


def test_openai_provider_payload_path_is_schema_compatible(tmp_path: Path) -> None:
    payload = StructuredExtractionPayload.model_validate_json(
        Path("tests/fixtures/openai/structured_response.json").read_text(encoding="utf-8")
    )
    jsonl = tmp_path / "normalized.jsonl"
    jsonl.write_text(
        '{"id":"r1","source_id":"s1","source_path":"meeting.md","source_type":"markdown",'
        '"title":"Meeting","text":"Decision: Use Neo4j as canonical graph.",'
        '"ordinal":0,"sha256":"abc"}\n',
        encoding="utf-8",
    )

    graph = LLMStructuredExtractor(provider=FakeProvider(payload)).extract(jsonl, "acme-poc")

    assert len(graph.entities) == 2
    assert len(graph.assertions) == 1
    assert graph.assertions[0].extractor == "openai_structured_extractor"


def test_openai_strict_schema_forbids_extra_properties_recursively() -> None:
    schema = openai_strict_json_schema(StructuredExtractionPayload.model_json_schema())

    object_nodes = _object_schema_nodes(schema)

    assert object_nodes
    assert all(node.get("additionalProperties") is False for node in object_nodes)
    assert all(node.get("required") == list(node["properties"]) for node in object_nodes)
    assert not _contains_schema_key(schema, "default")


def test_validation_rejects_invalid_predicate(tmp_path: Path) -> None:
    project = scaffold_project(
        tmp_path / "acme-poc",
        "acme-poc",
        with_docker=False,
        with_markdown_wiki=True,
        force=False,
    )
    graph = parse_graphify_graph(
        Path("tests/fixtures/ontology/invalid_predicate_graph.json"),
        "acme-poc",
    )

    result = OntologyValidator(project).validate(graph)

    assert result.rejected
    assert result.graph.assertions == []
    assert (project / "data/processed/rejected/rejections.jsonl").exists()
    rejection_text = (project / "data/processed/rejected/rejections.jsonl").read_text(
        encoding="utf-8"
    )
    assert "predicate" in rejection_text
    assert (project / "data/processed/rejected/summary.md").exists()


def test_validation_removes_stale_rejection_outputs(tmp_path: Path) -> None:
    project = scaffold_project(
        tmp_path / "acme-poc",
        "acme-poc",
        with_docker=False,
        with_markdown_wiki=True,
        force=False,
    )
    validator = OntologyValidator(project)
    validator.validate(
        parse_graphify_graph(
            Path("tests/fixtures/ontology/invalid_predicate_graph.json"), "acme-poc"
        )
    )

    validator.validate(parse_graphify_graph(Path("tests/fixtures/graphify/graph.json"), "acme-poc"))

    rejected = project / "data/processed/rejected"
    assert not (rejected / "rejections.jsonl").exists()
    assert not (rejected / "summary.md").exists()


def test_wiki_export_includes_relationships_and_summary(tmp_path: Path) -> None:
    graph = parse_graphify_graph(Path("tests/fixtures/graphify/graph.json"), "acme-poc")

    files = WikiExporter().export(graph, tmp_path / "wiki")

    assert tmp_path / "wiki/graph-summary.md" in files
    assert tmp_path / "wiki/graph-summary.html" in files
    assert tmp_path / "wiki/index.html" in files
    assert any(path.parent.name == "sources" for path in files)
    page = next(path for path in files if path.parent.name == "entities")
    text = page.read_text(encoding="utf-8")
    assert "## Outgoing Relationships" in text
    assert "## Incoming Relationships" in text
    rendered = (tmp_path / "wiki/index.html").read_text(encoding="utf-8")
    assert "<h1>Acme Poc Wiki</h1>" in rendered
    assert 'href="./architecture.html"' in rendered


def test_wiki_export_removes_stale_generated_pages(tmp_path: Path) -> None:
    graph = parse_graphify_graph(Path("tests/fixtures/graphify/graph.json"), "acme-poc")
    wiki = tmp_path / "wiki"

    WikiExporter().export(graph, wiki)
    stale = wiki / "entities" / "stale.md"
    stale_html = wiki / "entities" / "stale.html"
    stale.write_text("# stale\n", encoding="utf-8")
    stale_html.write_text("<h1>stale</h1>\n", encoding="utf-8")
    WikiExporter().export(graph, wiki)

    assert not stale.exists()
    assert not stale_html.exists()


@pytest.mark.neo4j
def test_neo4j_repository_round_trip() -> None:
    required = ["NEO4J_URI", "NEO4J_DATABASE", "NEO4J_USER", "NEO4J_PASSWORD"]
    if not all(os.getenv(name) for name in required):
        pytest.skip("Neo4j env vars are not configured.")
    if shutil.which("nc") and os.system("nc -z localhost 7687 >/dev/null 2>&1") != 0:
        pytest.skip("Neo4j is not reachable on localhost:7687.")

    graph = parse_graphify_graph(Path("tests/fixtures/graphify/graph.json"), "acme-poc")
    client = Neo4jClient(
        Neo4jConnection(
            uri=os.environ["NEO4J_URI"],
            username=os.environ["NEO4J_USER"],
            password=os.environ["NEO4J_PASSWORD"],
            database=os.environ["NEO4J_DATABASE"],
        )
    )
    try:
        repository = Neo4jGraphRepository(client)
        repository.bootstrap()
        repository.upsert_graph(graph)
        stored = repository.read_graph("acme-poc")
    finally:
        client.close()

    assert stored.entities
    assert stored.assertions


def _object_schema_nodes(node: object) -> list[dict[str, object]]:
    if isinstance(node, list):
        result: list[dict[str, object]] = []
        for item in node:
            result.extend(_object_schema_nodes(item))
        return result
    if not isinstance(node, dict):
        return []

    result = [node] if isinstance(node.get("properties"), dict) else []
    for value in node.values():
        result.extend(_object_schema_nodes(value))
    return result


def _contains_schema_key(node: object, key: str) -> bool:
    if isinstance(node, list):
        return any(_contains_schema_key(item, key) for item in node)
    if isinstance(node, dict):
        return key in node or any(_contains_schema_key(value, key) for value in node.values())
    return False
