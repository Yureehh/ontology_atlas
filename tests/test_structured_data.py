from __future__ import annotations

import builtins
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from company_ontology_agent.config.project_config import DatasetConfig, default_config
from company_ontology_agent.graph.models import (
    Assertion,
    Entity,
    EntityType,
    ExtractedGraph,
    entity_graph_kind,
)
from company_ontology_agent.graph.repository import Neo4jGraphRepository
from company_ontology_agent.portal.builder import PortalBuilder
from company_ontology_agent.resolution.entity_resolution import EntityResolver
from company_ontology_agent.structured.projection import build_structured_graph
from company_ontology_agent.wiki.exporter import WikiExporter


def test_csv_mapping_projects_generic_business_graph(tmp_path: Path) -> None:
    config = _project_with_csv_dataset(tmp_path)

    graph = build_structured_graph(tmp_path, config)

    records = [entity for entity in graph.entities if not entity.metadata.get("semantic_summary")]
    summaries = [entity for entity in graph.entities if entity.metadata.get("semantic_summary")]
    assert len(records) == 2
    assert len(summaries) == 1
    assert len(graph.assertions) == 3
    entity = records[0]
    assert entity.type.value == "BusinessEntity"
    assert entity.metadata["domain"] == "people"
    assert entity.metadata["dataset"] == "data_reply_people"
    assert entity.metadata["mapped_type"] == "PersonRecord"
    assert entity.metadata["email"] == "[redacted]"
    assert entity.metadata["years_experience"] in {3, 12}
    assert "years_experience" in entity.metadata["queryable_properties"]
    assert "email" not in entity.metadata["queryable_properties"]
    assert summaries[0].name == "PersonRecord in data_reply_people"
    assert summaries[0].metadata["record_count"] == 2
    assert summaries[0].metadata["authority"] == "authoritative"
    assert {assertion.predicate for assertion in graph.assertions} == {
        "member_of",
        "reports_to",
    }


def test_generic_business_entity_is_not_a_business_data_node() -> None:
    extracted = Entity(
        id="concept",
        type=EntityType.business_entity,
        name="Customer strategy",
        normalized_name="customer strategy",
        extraction_source="graphify_semantic",
    )
    structured = extracted.model_copy(
        update={
            "id": "team",
            "name": "Team Liquid",
            "normalized_name": "team liquid",
            "extraction_source": "structured_connector",
            "metadata": {"mapped_type": "Team", "connector": "parquet"},
        }
    )

    assert entity_graph_kind(extracted) == "repo"
    assert entity_graph_kind(structured) == "data"


def test_structured_identity_prefers_human_name_across_datasets() -> None:
    opaque = Entity(
        id="mapping-team",
        type=EntityType.business_entity,
        name="oe:team:0dbb780176ecad18f17292d1f5653af",
        normalized_name="oe team 0dbb780176ecad18f17292d1f5653af",
        extraction_source="structured_connector",
        source_path="models/team_league_mapping.parquet#row=1",
        metadata={
            "domain": "league_of_legends",
            "mapped_type": "Team",
            "record_key": "123",
            "dataset": "team_league_mapping",
            "connector": "parquet",
        },
    )
    named = opaque.model_copy(
        update={
            "id": "raw-team",
            "name": "Team Liquid",
            "normalized_name": "team liquid",
            "source_path": "models/matches.parquet#row=8",
            "metadata": {
                **opaque.metadata,
                "dataset": "matches",
            },
        }
    )

    resolved, _ = EntityResolver().resolve(
        ExtractedGraph(project_slug="oracle", entities=[opaque, named])
    )

    assert len(resolved.entities) == 1
    assert resolved.entities[0].name == "Team Liquid"
    assert opaque.name in resolved.entities[0].aliases
    assert resolved.entities[0].metadata["datasets"] == ["matches", "team_league_mapping"]
    assert resolved.entities[0].metadata["dataset_sources"] == {
        "matches": ["models/matches.parquet#row=8"],
        "team_league_mapping": ["models/team_league_mapping.parquet#row=1"],
    }


def test_canonical_entity_ids_are_isolated_by_project() -> None:
    entity = Entity(
        id="source-team",
        type=EntityType.business_entity,
        name="Team Liquid",
        normalized_name="team liquid",
        extraction_source="structured_connector",
        metadata={
            "domain": "league_of_legends",
            "mapped_type": "Team",
            "record_key": "team-liquid",
        },
    )

    target = entity.model_copy(
        update={
            "id": "target-team",
            "name": "Fnatic",
            "normalized_name": "fnatic",
            "metadata": {**entity.metadata, "record_key": "fnatic"},
        }
    )
    assertion = Assertion(
        id="same-source-assertion",
        predicate="team_in_league",
        subject_id=entity.id,
        object_id=target.id,
        evidence_span_id="",
        confidence=1.0,
        extractor="structured_connector",
    )
    first, _ = EntityResolver().resolve(
        ExtractedGraph(
            project_slug="project-a", entities=[entity, target], assertions=[assertion]
        )
    )
    second, _ = EntityResolver().resolve(
        ExtractedGraph(
            project_slug="project-b", entities=[entity, target], assertions=[assertion]
        )
    )

    assert first.entities[0].id != second.entities[0].id
    assert first.assertions[0].id != second.assertions[0].id


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

    records = [entity for entity in graph.entities if not entity.metadata.get("semantic_summary")]
    assert {entity.name for entity in records} == {"Quarterly Review", "Risk Review"}
    assert {entity.metadata["connector"] for entity in records} == {"jsonl", "sqlite"}


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
    assert {assertion.predicate for assertion in graph.assertions} >= {
        "model_artifact_generated",
        "prediction_for_match",
        "member_of",
    }
    match_entities = [
        entity
        for entity in graph.entities
        if entity.metadata["mapped_type"] == "Match"
        and not entity.metadata.get("semantic_summary")
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
    graph_json = json.loads((tmp_path / "portal" / "graph.json").read_text(encoding="utf-8"))
    wiki_index = (tmp_path / "wiki" / "index.html").read_text(encoding="utf-8")
    wiki_data_graph = (tmp_path / "wiki" / "data-graph.html").read_text(encoding="utf-8")
    assert 'id="domain"' not in html
    assert 'id="extractor"' not in html
    assert 'id="layer"' in html
    assert 'id="dataset"' in html
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
        "person_id,full_name,email,title,manager_id,years_experience\n"
        "p1,Ada Rossi,ada@example.com,Lead,,12\n"
        "p2,Luca Bianchi,luca@example.com,Engineer,p1,3\n",
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
        "    properties: [email, title, years_experience]\n"
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
