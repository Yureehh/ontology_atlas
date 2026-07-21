from __future__ import annotations

import builtins
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from company_ontology_agent.config.project_config import DatasetConfig, default_config
from company_ontology_agent.graph.repository import Neo4jGraphRepository
from company_ontology_agent.portal.builder import PortalBuilder
from company_ontology_agent.structured.projection import build_structured_graph
from company_ontology_agent.wiki.exporter import WikiExporter


def test_csv_mapping_projects_generic_business_graph(tmp_path: Path) -> None:
    config = _project_with_csv_dataset(tmp_path)

    graph = build_structured_graph(tmp_path, config)

    assert len(graph.entities) == 2
    assert len(graph.assertions) == 1
    entity = graph.entities[0]
    assert entity.type.value == "BusinessEntity"
    assert entity.metadata["domain"] == "people"
    assert entity.metadata["dataset"] == "data_reply_people"
    assert entity.metadata["mapped_type"] == "PersonRecord"
    assert entity.metadata["email"] == "[redacted]"
    assert graph.assertions[0].predicate == "reports_to"


def test_jsonl_and_sqlite_connectors_project_records(tmp_path: Path) -> None:
    _write_mapping(tmp_path)
    json_path = tmp_path / "events.jsonl"
    json_path.write_text(
        json.dumps({"event_id": "e1", "event_name": "Quarterly Review"}) + "\n",
        encoding="utf-8",
    )
    sqlite_path = tmp_path / "records.sqlite"
    with sqlite3.connect(sqlite_path) as connection:
        connection.execute("CREATE TABLE events (event_id TEXT, event_name TEXT)")
        connection.execute("INSERT INTO events VALUES ('e2', 'Risk Review')")
    config = default_config("data_reply_poc")
    config.datasets = [
        DatasetConfig(
            name="data_reply_json_events",
            domain="operations",
            connector="jsonl",
            path=str(json_path),
            mapping=str(tmp_path / "event_mapping.yaml"),
        ),
        DatasetConfig(
            name="data_reply_sqlite_events",
            domain="operations",
            connector="sqlite",
            path=str(sqlite_path),
            include_tables=["events"],
            mapping=str(tmp_path / "event_mapping.yaml"),
        ),
    ]

    graph = build_structured_graph(tmp_path, config)

    assert {entity.name for entity in graph.entities} == {"Quarterly Review", "Risk Review"}
    assert {entity.metadata["connector"] for entity in graph.entities} == {"jsonl", "sqlite"}


def test_parquet_connector_projects_composite_keys_and_template_names(tmp_path: Path) -> None:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    parquet_path = tmp_path / "predictions.parquet"
    pq.write_table(
        pa.table(
            {
                "gameid": ["g1", "g1"],
                "side": ["Blue", "Red"],
                "model_name": ["LightGBM", "LightGBM"],
                "prediction": [1, 0],
                "proba": [0.61, 0.39],
            }
        ),
        parquet_path,
    )
    (tmp_path / "prediction_mapping.yaml").write_text(
        "entities:\n"
        "  prediction:\n"
        "    source: predictions\n"
        "    type: Prediction\n"
        "    key: [gameid, side]\n"
        '    name: "Prediction {gameid} {side}"\n'
        "    properties: [prediction, proba]\n"
        "  match:\n"
        "    source: predictions\n"
        "    type: Match\n"
        "    key: gameid\n"
        "    name: gameid\n"
        "  model_artifact:\n"
        "    source: predictions\n"
        "    type: ModelArtifact\n"
        "    key: model_name\n"
        "    name: model_name\n"
        "relationships:\n"
        "  - type: PREDICTION_FOR_MATCH\n"
        "    from_entity: prediction\n"
        "    from_key: gameid\n"
        "    to_entity: match\n"
        "    to_key: gameid\n"
        "  - type: MODEL_ARTIFACT_GENERATED\n"
        "    from_entity: model_artifact\n"
        "    from_key: [gameid, side]\n"
        "    to_entity: prediction\n"
        "    to_key: prediction_key\n",
        encoding="utf-8",
    )
    config = default_config("oracle_bets_data")
    config.datasets = [
        DatasetConfig(
            name="oracle_bets_predictions",
            domain="betting",
            connector="parquet",
            path=str(parquet_path),
            mapping=str(tmp_path / "prediction_mapping.yaml"),
            required_columns=["gameid", "side", "prediction"],
        )
    ]

    graph = build_structured_graph(tmp_path, config)

    names = {entity.name for entity in graph.entities}
    assert {"Prediction g1 Blue", "Prediction g1 Red", "g1"}.issubset(names)
    assert {assertion.predicate for assertion in graph.assertions} == {
        "model_artifact_generated",
        "prediction_for_match",
    }
    match_entities = [
        entity for entity in graph.entities if entity.metadata["mapped_type"] == "Match"
    ]
    assert len(match_entities) == 1


def test_parquet_connector_missing_extra_error_is_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parquet_path = tmp_path / "empty.parquet"
    parquet_path.write_bytes(b"not parquet")
    _write_mapping(tmp_path)
    config = default_config("missing_parquet_extra")
    config.datasets = [
        DatasetConfig(
            name="demo",
            domain="demo",
            connector="parquet",
            path=str(parquet_path),
            mapping=str(tmp_path / "people_mapping.yaml"),
        )
    ]
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("pyarrow"):
            raise ImportError("blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match=r"\.\[parquet\]"):
        build_structured_graph(tmp_path, config)


def test_required_columns_fail_fast(tmp_path: Path) -> None:
    _write_mapping(tmp_path)
    csv_path = tmp_path / "people.csv"
    csv_path.write_text("person_id,full_name\np1,Ada\n", encoding="utf-8")
    config = default_config("required_columns")
    config.datasets = [
        DatasetConfig(
            name="people",
            domain="people",
            connector="csv",
            path=str(csv_path),
            mapping=str(tmp_path / "people_mapping.yaml"),
            required_columns=["email"],
        )
    ]

    with pytest.raises(ValueError, match="missing required columns"):
        build_structured_graph(tmp_path, config)


def test_portal_and_wiki_include_domain_dataset_filters(tmp_path: Path) -> None:
    config = _project_with_csv_dataset(tmp_path)
    graph = build_structured_graph(tmp_path, config)

    PortalBuilder().build(graph, tmp_path, tmp_path / "portal")
    wiki_files = WikiExporter().export(
        graph,
        tmp_path / "wiki",
        display_name="Ontology Atlas Oracle Bets Ontology",
    )

    # Structured data uses the Business data filter in the single Explore surface.
    html = (tmp_path / "portal" / "explore.html").read_text(encoding="utf-8")
    legacy_data = (tmp_path / "portal" / "data-graph.html").read_text(encoding="utf-8")
    graph_json = json.loads((tmp_path / "portal" / "graph.json").read_text(encoding="utf-8"))
    wiki_index = (tmp_path / "wiki" / "index.html").read_text(encoding="utf-8")
    wiki_data_graph = (tmp_path / "wiki" / "data-graph.html").read_text(encoding="utf-8")
    assert 'id="domain"' not in html
    assert 'id="extractor"' not in html
    assert 'id="layer"' in html
    assert 'id="dataset"' in html
    assert "explore.html#layer=data" in legacy_data
    assert 'id="predicate"' in html
    assert graph_json["nodes"][0]["domain"] == "people"
    assert graph_json["nodes"][0]["graph_kind"] == "data"
    assert graph_json["links"][0]["graph_kind"] == "data"
    assert "Oracle Bets Wiki" in wiki_index
    assert "data_reply_poc Wiki" not in wiki_index
    assert '<a href="./graph-summary.html">Graph summary</a>' in wiki_index
    assert "Oracle Bets Data Graph" in wiki_data_graph
    assert "data_reply_people" in wiki_data_graph
    assert "PersonRecord" in wiki_data_graph
    assert tmp_path / "wiki" / "domains" / "people.md" in wiki_files
    assert tmp_path / "wiki" / "datasets" / "data-reply-people.md" in wiki_files


def test_neo4j_prune_marks_and_deletes_stale_project_nodes(tmp_path: Path) -> None:
    config = _project_with_csv_dataset(tmp_path)
    graph = build_structured_graph(tmp_path, config)
    client = FakeNeo4jClient()
    repository = Neo4jGraphRepository(client)

    repository.upsert_graph(graph, prune_mode="stale")
    repository.prune_graph(graph, "delete")

    statements = "\n".join(statement for statement, _ in client.calls)
    assert "SET e.stale = true" in statements
    assert "SET a.stale = true" in statements
    assert "DETACH DELETE a" in statements
    assert "DETACH DELETE e" in statements
    assert "MERGE (d:Domain" in statements
    assert "MERGE (ds:Dataset" in statements


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


def _project_with_csv_dataset(tmp_path: Path):
    data_path = tmp_path / "people.csv"
    data_path.write_text(
        "person_id,full_name,email,title,manager_id\n"
        "p1,Ada Rossi,ada@example.com,Lead,\n"
        "p2,Luca Bianchi,luca@example.com,Engineer,p1\n",
        encoding="utf-8",
    )
    _write_mapping(tmp_path)
    config = default_config("data_reply_poc")
    config.datasets = [
        DatasetConfig(
            name="data_reply_people",
            domain="people",
            connector="csv",
            path=str(data_path),
            mapping=str(tmp_path / "people_mapping.yaml"),
        )
    ]
    return config


def _write_mapping(tmp_path: Path) -> None:
    (tmp_path / "people_mapping.yaml").write_text(
        "entities:\n"
        "  person:\n"
        "    source: people\n"
        "    type: PersonRecord\n"
        "    key: person_id\n"
        "    name: full_name\n"
        "    properties: [email, title]\n"
        "    redact: [email]\n"
        "relationships:\n"
        "  - type: REPORTS_TO\n"
        "    from_entity: person\n"
        "    from_key: manager_id\n"
        "    to_entity: person\n"
        "    to_key: person_id\n",
        encoding="utf-8",
    )
    (tmp_path / "event_mapping.yaml").write_text(
        "entities:\n"
        "  event:\n"
        "    source: events\n"
        "    type: BusinessEvent\n"
        "    key: event_id\n"
        "    name: event_name\n"
        "relationships: []\n",
        encoding="utf-8",
    )
