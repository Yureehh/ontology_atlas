from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from itertools import batched
from pathlib import Path
from typing import Protocol

from company_ontology_agent.graph.cypher import CONSTRAINTS
from company_ontology_agent.graph.models import ExtractedGraph
from company_ontology_agent.graph.neo4j_client import Neo4jClient
from company_ontology_agent.structured.models import PruneMode


class GraphRepository(Protocol):
    def bootstrap(self) -> None: ...

    def upsert_graph(self, graph: ExtractedGraph, prune_mode: PruneMode = "none") -> None: ...

    def prune_graph(self, graph: ExtractedGraph, prune_mode: PruneMode) -> None: ...

    def read_graph(self, project_slug: str) -> ExtractedGraph: ...


class JsonGraphRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.prev_path = path.with_name("graph.prev.json")
        self.fingerprint_path = path.with_name("scope-fingerprint.json")
        self.prev_fingerprint_path = path.with_name("scope-fingerprint.prev.json")

    def bootstrap(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("{}", encoding="utf-8")

    def snapshot_previous(self) -> None:
        """Copy the current graph.json to graph.prev.json before it is overwritten.

        This is the baseline for run-to-run diffing. Called before a replace so the next
        build can compare the freshly-built graph against the last committed one.
        """
        if self.path.exists():
            text = self.path.read_text(encoding="utf-8").strip()
            if text and text != "{}":
                self.prev_path.write_text(text, encoding="utf-8")
                if self.fingerprint_path.exists():
                    self.prev_fingerprint_path.write_text(
                        self.fingerprint_path.read_text(encoding="utf-8"), encoding="utf-8"
                    )

    def read_previous(self, project_slug: str) -> ExtractedGraph | None:
        """Return the previous run's graph, or None when there is no baseline yet."""
        if not self.prev_path.exists():
            return None
        text = self.prev_path.read_text(encoding="utf-8").strip()
        if not text or text == "{}":
            return None
        data = json.loads(text)
        return ExtractedGraph.model_validate(data) if data else None

    def upsert_graph(self, graph: ExtractedGraph, prune_mode: PruneMode = "none") -> None:
        self.bootstrap()
        existing = self.read_graph(graph.project_slug)
        merged = existing.merge(graph)
        self.path.write_text(merged.model_dump_json(indent=2), encoding="utf-8")

    def prune_graph(self, graph: ExtractedGraph, prune_mode: PruneMode) -> None:
        if prune_mode == "delete":
            self.replace_graph(graph)

    def replace_graph(self, graph: ExtractedGraph) -> None:
        self.bootstrap()
        self.path.write_text(graph.model_dump_json(indent=2), encoding="utf-8")

    def read_graph(self, project_slug: str) -> ExtractedGraph:
        if not self.path.exists() or not self.path.read_text(encoding="utf-8").strip():
            return ExtractedGraph(project_slug=project_slug)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not data:
            return ExtractedGraph(project_slug=project_slug)
        return ExtractedGraph.model_validate(data)


class Neo4jGraphRepository:
    def __init__(self, client: Neo4jClient, *, write_visual_relationships: bool = True) -> None:
        self.client = client
        self.write_visual_relationships = write_visual_relationships

    def bootstrap(self) -> None:
        for statement in [part.strip() for part in CONSTRAINTS.split(";") if part.strip()]:
            self.client.execute(statement)

    def upsert_graph(self, graph: ExtractedGraph, prune_mode: PruneMode = "none") -> None:
        seen_at = datetime.now(UTC).isoformat()
        self.client.execute(
            """
            MERGE (p:Project:DemoProject {slug: $slug})
            SET p.name = $slug,
                p.caption = $slug,
                p.display_name = $slug,
                p.demo_node = true,
                p.seen_at = $seen_at
            """,
            {"slug": graph.project_slug, "seen_at": seen_at},
        )
        _execute_batches(
            self.client,
            """
            UNWIND $rows AS row
            MERGE (s:Source {id: row.id})
            SET s += row.props
            WITH s
            MATCH (p:Project {slug: $project_slug})
            MERGE (p)-[:HAS_SOURCE]->(s)
            """,
            [{"id": source.id, "props": source.model_dump()} for source in graph.sources],
            project_slug=graph.project_slug,
        )
        _execute_batches(
            self.client,
            """
            UNWIND $rows AS row
            MERGE (ss:SourceSpan {id: row.id})
            SET ss += row.props
            WITH ss, row
            MATCH (s:Source {id: row.source_id})
            MERGE (s)-[:HAS_SPAN]->(ss)
            """,
            [
                {"id": span.id, "props": span.model_dump(), "source_id": span.source_id}
                for span in graph.source_spans
            ],
        )
        _execute_batches(
            self.client,
            """
            UNWIND $rows AS row
            MERGE (c:Chunk {id: row.id})
            SET c += row.props
            WITH c, row
            MATCH (ss:SourceSpan {id: row.span_id})
            MERGE (c)-[:DERIVED_FROM]->(ss)
            """,
            [
                {"id": chunk.id, "props": chunk.model_dump(), "span_id": chunk.source_span_id}
                for chunk in graph.chunks
            ],
        )
        entity_rows_by_label: dict[str, list[dict[str, object]]] = defaultdict(list)
        datasets_by_id: dict[str, dict[str, object]] = {}
        dataset_memberships: list[dict[str, object]] = []
        graphify_node_rows: list[dict[str, object]] = []
        for entity in graph.entities:
            labels = f"DemoNode:Entity:{entity.type.value}"
            # Structured rows also get their configured mapped type as a Neo4j label.
            mapped = str(entity.metadata.get("mapped_type") or "")
            if mapped and mapped != entity.type.value and mapped.isidentifier():
                labels += f":{mapped}"
            props = _neo4j_props(
                {
                    **entity.model_dump(mode="json"),
                    "caption": entity.name,
                    "display_name": entity.name,
                    "demo_node": True,
                    "stale": False,
                    "seen_at": seen_at,
                    "domain": entity.metadata.get("domain"),
                    "dataset": entity.metadata.get("dataset"),
                    "connector": entity.metadata.get("connector"),
                    "mapped_type": entity.metadata.get("mapped_type"),
                    **_queryable_entity_props(entity.metadata),
                }
            )
            entity_rows_by_label[labels].append({"id": entity.id, "props": props})
            domain = entity.metadata.get("domain")
            dataset = entity.metadata.get("dataset")
            if isinstance(domain, str) and isinstance(dataset, str):
                dataset_id = f"{graph.project_slug}:{domain}:{dataset}"
                datasets_by_id[dataset_id] = {
                    "project_slug": graph.project_slug,
                    "domain": domain,
                    "dataset": dataset,
                    "connector": entity.metadata.get("connector"),
                    "domain_id": f"{graph.project_slug}:{domain}",
                    "dataset_id": dataset_id,
                }
                dataset_memberships.append({"dataset_id": dataset_id, "entity_id": entity.id})
            if entity.graphify_id:
                graphify_node_rows.append(
                    {
                        "id": entity.graphify_id,
                        "entity_id": entity.id,
                        "props": _neo4j_props(
                            {
                                "id": entity.graphify_id,
                                "name": entity.name,
                                "entity_id": entity.id,
                                "type": entity.type.value,
                                "source_path": entity.source_path,
                                "community": entity.community,
                                **entity.metadata,
                            }
                        ),
                    }
                )
        for labels, rows in entity_rows_by_label.items():
            _execute_batches(
                self.client,
                f"""
                UNWIND $rows AS row
                MERGE (e:{labels} {{id: row.id}})
                SET e += row.props
                WITH e
                MATCH (p:Project {{slug: $project_slug}})
                MERGE (p)-[r:HAS_ENTITY]->(e)
                SET r.caption = "has entity", r.demo_relationship = true
                """,
                rows,
                project_slug=graph.project_slug,
            )
        _execute_batches(
            self.client,
            """
            UNWIND $rows AS row
            MATCH (p:Project {slug: row.project_slug})
            MERGE (d:Domain {id: row.domain_id})
            SET d.name = row.domain, d.caption = row.domain,
                d.project_slug = row.project_slug
            MERGE (ds:Dataset {id: row.dataset_id})
            SET ds.name = row.dataset, ds.caption = row.dataset,
                ds.domain = row.domain, ds.project_slug = row.project_slug,
                ds.connector = row.connector
            MERGE (p)-[:HAS_DOMAIN]->(d)
            MERGE (d)-[:HAS_DATASET]->(ds)
            """,
            list(datasets_by_id.values()),
        )
        _execute_batches(
            self.client,
            """
            UNWIND $rows AS row
            MATCH (ds:Dataset {id: row.dataset_id})
            MATCH (e:Entity {id: row.entity_id})
            MERGE (ds)-[:HAS_ENTITY]->(e)
            """,
            dataset_memberships,
        )
        _execute_batches(
            self.client,
            """
            UNWIND $rows AS row
            MERGE (g:GraphifyNode {id: row.id})
            SET g += row.props
            WITH g, row
            MATCH (e:Entity {id: row.entity_id})
            MERGE (e)-[:DERIVED_FROM_GRAPHIFY]->(g)
            """,
            graphify_node_rows,
        )
        assertion_rows: list[dict[str, object]] = []
        graphify_edge_rows: list[dict[str, object]] = []
        visual_rows: dict[str, list[dict[str, object]]] = defaultdict(list)
        for assertion in graph.assertions:
            assertion_rows.append(
                {
                    "id": assertion.id,
                    "props": _neo4j_props(assertion.model_dump(mode="json")),
                    "predicate": assertion.predicate,
                    "seen_at": seen_at,
                    "project_slug": graph.project_slug,
                    "subject_id": assertion.subject_id,
                    "object_id": assertion.object_id,
                    "span_id": assertion.evidence_span_id,
                }
            )
            if assertion.graphify_id:
                graphify_edge_rows.append(
                    {
                        "id": assertion.graphify_id,
                        "assertion_id": assertion.id,
                        "subject_id": assertion.subject_id,
                        "object_id": assertion.object_id,
                        "props": _neo4j_props(
                            {
                                "id": assertion.graphify_id,
                                "assertion_id": assertion.id,
                                "predicate": assertion.predicate,
                                "source_path": assertion.source_path,
                                "community": assertion.community,
                                "confidence": assertion.confidence,
                                **assertion.metadata,
                            }
                        ),
                    }
                )
            if self.write_visual_relationships:
                rel_type = _visual_relationship_type(assertion.predicate)
                visual_rows[rel_type].append(
                    {
                        "project_slug": graph.project_slug,
                        "subject_id": assertion.subject_id,
                        "object_id": assertion.object_id,
                        "assertion_id": assertion.id,
                        "predicate": assertion.predicate,
                        "confidence": assertion.confidence,
                        "evidence_span_id": assertion.evidence_span_id,
                        "extractor": assertion.extractor,
                        "seen_at": seen_at,
                    }
                )
        _execute_batches(
            self.client,
            """
            UNWIND $rows AS row
            MERGE (a:Assertion {id: row.id})
            SET a += row.props, a.caption = row.predicate,
                a.display_name = row.predicate, a.stale = false, a.seen_at = row.seen_at
            WITH a, row
            MATCH (p:Project {slug: row.project_slug})
            MERGE (p)-[:HAS_ASSERTION]->(a)
            WITH a, row
            MATCH (subject:Entity {id: row.subject_id})
            MERGE (a)-[:SUBJECT]->(subject)
            WITH a, row
            MATCH (object:Entity {id: row.object_id})
            MERGE (a)-[:OBJECT]->(object)
            WITH a, row
            OPTIONAL MATCH (span:SourceSpan {id: row.span_id})
            FOREACH (_ IN CASE WHEN span IS NULL THEN [] ELSE [1] END |
                MERGE (a)-[:EVIDENCED_BY]->(span)
            )
            """,
            assertion_rows,
        )
        _execute_batches(
            self.client,
            """
            UNWIND $rows AS row
            MERGE (ge:GraphifyEdge {id: row.id})
            SET ge += row.props
            WITH ge, row
            MATCH (a:Assertion {id: row.assertion_id})
            MERGE (a)-[:DERIVED_FROM_GRAPHIFY]->(ge)
            WITH ge, row
            OPTIONAL MATCH (subject:Entity {id: row.subject_id})-[:DERIVED_FROM_GRAPHIFY]->
                (gs:GraphifyNode)
            OPTIONAL MATCH (object:Entity {id: row.object_id})-[:DERIVED_FROM_GRAPHIFY]->
                (go:GraphifyNode)
            FOREACH (_ IN CASE WHEN gs IS NULL OR go IS NULL THEN [] ELSE [1] END |
                MERGE (gs)-[:GRAPHIFY_RELATES {edge_id: row.id}]->(go)
            )
            """,
            graphify_edge_rows,
        )
        for rel_type, rows in visual_rows.items():
            _execute_batches(
                self.client,
                f"""
                UNWIND $rows AS row
                MATCH (subject:Entity {{id: row.subject_id}})
                MATCH (object:Entity {{id: row.object_id}})
                MERGE (subject)-[r:{rel_type} {{assertion_id: row.assertion_id}}]->(object)
                SET r.predicate = row.predicate, r.confidence = row.confidence,
                    r.evidence_span_id = row.evidence_span_id, r.extractor = row.extractor,
                    r.project_slug = row.project_slug,
                    r.caption = row.predicate, r.demo_relationship = true,
                    r.stale = false, r.seen_at = row.seen_at
                """,
                rows,
            )
        if prune_mode != "none":
            self.prune_graph(graph, prune_mode)

    def prune_graph(self, graph: ExtractedGraph, prune_mode: PruneMode) -> None:
        if prune_mode == "none":
            return
        entity_ids = [entity.id for entity in graph.entities]
        assertion_ids = [assertion.id for assertion in graph.assertions]
        parameters: dict[str, object] = {
            "project_slug": graph.project_slug,
            "entity_ids": entity_ids,
            "assertion_ids": assertion_ids,
        }
        if prune_mode == "stale":
            self.client.execute(
                """
                MATCH (:Project {slug: $project_slug})-[:HAS_ENTITY]->(e:Entity)
                WHERE NOT e.id IN $entity_ids
                SET e.stale = true, e.status = "superseded"
                """,
                parameters,
            )
            self.client.execute(
                """
                MATCH (:Project {slug: $project_slug})-[:HAS_ASSERTION]->(a:Assertion)
                WHERE NOT a.id IN $assertion_ids
                SET a.stale = true, a.status = "superseded"
                """,
                parameters,
            )
            self.client.execute(
                """
                MATCH (:Project {slug: $project_slug})-[:HAS_ENTITY]->(:Entity)-[r]->(:Entity)
                WHERE r.assertion_id IS NOT NULL AND NOT r.assertion_id IN $assertion_ids
                SET r.stale = true, r.status = "superseded"
                """,
                parameters,
            )
            return
        if prune_mode == "delete":
            self.client.execute(
                """
                MATCH (:Project {slug: $project_slug})-[:HAS_ASSERTION]->(a:Assertion)
                WHERE NOT a.id IN $assertion_ids
                DETACH DELETE a
                """,
                parameters,
            )
            self.client.execute(
                """
                MATCH (:Project {slug: $project_slug})-[rel:HAS_ENTITY]->(e:Entity)
                WHERE NOT e.id IN $entity_ids
                DETACH DELETE e
                """,
                parameters,
            )
            return
        raise ValueError(f"Unsupported prune mode: {prune_mode}")

    def read_graph(self, project_slug: str) -> ExtractedGraph:
        source_rows = self.client.query(
            """
            MATCH (:Project {slug: $slug})-[:HAS_SOURCE]->(s:Source)
            RETURN properties(s) AS props
            """,
            {"slug": project_slug},
        )
        span_rows = self.client.query(
            """
            MATCH (:Project {slug: $slug})-[:HAS_SOURCE]->(:Source)-[:HAS_SPAN]->(ss:SourceSpan)
            RETURN properties(ss) AS props
            """,
            {"slug": project_slug},
        )
        chunk_rows = self.client.query(
            """
            MATCH (:Project {slug: $slug})-[:HAS_SOURCE]->(:Source)-[:HAS_SPAN]->(ss:SourceSpan)
            MATCH (c:Chunk)-[:DERIVED_FROM]->(ss)
            RETURN properties(c) AS props
            """,
            {"slug": project_slug},
        )
        entity_rows = self.client.query(
            """
            MATCH (:Project {slug: $slug})-[:HAS_ENTITY]->(e:Entity)
            WHERE coalesce(e.stale, false) = false
            RETURN properties(e) AS props
            """,
            {"slug": project_slug},
        )
        assertion_rows = self.client.query(
            "MATCH (:Project {slug: $slug})-[:HAS_ASSERTION]->(a:Assertion) "
            "WHERE coalesce(a.stale, false) = false "
            "RETURN properties(a) AS props",
            {"slug": project_slug},
        )
        from company_ontology_agent.graph.models import Assertion, Chunk, Entity, Source, SourceSpan

        def restore(rows: list[dict[str, object]]) -> list[dict[str, object]]:
            return [_from_neo4j_props(row["props"]) for row in rows]

        return ExtractedGraph(
            project_slug=project_slug,
            sources=[Source.model_validate(props) for props in restore(source_rows)],
            source_spans=[SourceSpan.model_validate(props) for props in restore(span_rows)],
            chunks=[Chunk.model_validate(props) for props in restore(chunk_rows)],
            entities=[Entity.model_validate(props) for props in restore(entity_rows)],
            assertions=[Assertion.model_validate(props) for props in restore(assertion_rows)],
        )


def _visual_relationship_type(predicate: str) -> str:
    safe = "".join(character if character.isalnum() else "_" for character in predicate)
    safe = "_".join(part for part in safe.split("_") if part)
    return safe.upper() or "RELATED_TO"


def _from_neo4j_props(props: object) -> dict[str, object]:
    """Inverse of _neo4j_props: restore *_json string properties to their dicts.

    Without this, entities read back from Neo4j lose their metadata (mapped_type,
    dataset, domain...) and the wiki/portal degrade every structured row to a
    generic BusinessEntity.
    """
    if not isinstance(props, Mapping):
        return {}
    restored: dict[str, object] = {}
    for key, value in props.items():
        if key.endswith("_json") and isinstance(value, str):
            try:
                restored[key.removesuffix("_json")] = json.loads(value)
            except ValueError:
                restored[key] = value
        else:
            restored[key] = value
    return restored


def _neo4j_props(props: Mapping[str, object]) -> dict[str, object]:
    clean: dict[str, object] = {}
    for key, value in props.items():
        if value is None:
            continue
        if isinstance(value, Mapping):
            clean[f"{key}_json"] = json.dumps(value, sort_keys=True)
        else:
            clean[key] = value
    return clean


def _queryable_entity_props(metadata: Mapping[str, object]) -> dict[str, object]:
    declared = metadata.get("queryable_properties")
    if not isinstance(declared, list):
        return {}
    output: dict[str, object] = {}
    for name in declared:
        if not isinstance(name, str):
            continue
        value = metadata.get(name)
        if (
            value is None
            or value == "[redacted]"
            or not isinstance(value, str | int | float | bool)
        ):
            continue
        safe = "_".join(part for part in re_split_identifier(name) if part)
        if safe:
            output[f"attr_{safe.lower()}"] = value
    return output


def re_split_identifier(value: str) -> list[str]:
    return [
        "".join(character for character in part if character.isalnum())
        for part in value.replace("-", "_").split("_")
    ]


def _execute_batches(
    client: Neo4jClient,
    statement: str,
    rows: list[dict[str, object]],
    *,
    batch_size: int = 500,
    **parameters: object,
) -> None:
    for batch in batched(rows, batch_size):
        client.execute(statement, {**parameters, "rows": list(batch)})
