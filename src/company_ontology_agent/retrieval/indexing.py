from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import batched
from typing import Protocol, runtime_checkable

import neo4j
from pydantic import BaseModel, Field

from company_ontology_agent.graph.models import (
    Assertion,
    Entity,
    EntityType,
    ExtractedGraph,
    Source,
    SourceSpan,
    entity_graph_kind,
)
from company_ontology_agent.utils.display import (
    is_opaque_entity_name as _is_opaque_name,
)
from company_ontology_agent.utils.display import (
    is_test_entity as _is_test_entity,
)
from company_ontology_agent.utils.hashing import stable_hash
from company_ontology_agent.utils.ids import stable_id
from company_ontology_agent.utils.source_paths import artifact_path as _artifact_path

_CHUNK_SCHEMA_VERSION = 3


class KnowledgeChunk(BaseModel):
    id: str
    project_slug: str
    entity_id: str
    entity_ids: list[str] = Field(default_factory=list)
    title: str
    kind: str
    text: str
    content_hash: str
    source_span_ids: list[str] = Field(default_factory=list)
    source_paths: list[str] = Field(default_factory=list)
    evidence_level: str


@dataclass(frozen=True)
class IndexResult:
    indexed: int
    unchanged: int
    deleted: int
    total: int


class GraphClient(Protocol):
    def execute(self, statement: str, parameters: dict[str, object] | None = None) -> None: ...

    def query(
        self, statement: str, parameters: dict[str, object] | None = None
    ) -> list[dict[str, object]]: ...


class Embedder(Protocol):
    def embed_query(self, text: str) -> list[float]: ...


@runtime_checkable
class BatchEmbedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


_DEFAULT_INDEXED_TYPES = {
    EntityType.system,
    EntityType.package,
    EntityType.module,
    EntityType.class_,
    EntityType.api_endpoint,
    EntityType.data_model,
    EntityType.workflow,
    EntityType.data_store,
    EntityType.external_service,
}


def build_knowledge_chunks(
    graph: ExtractedGraph,
    *,
    entity_limit: int = 200,
    entity_types: Sequence[str] = (),
    document_chunk_limit: int = 1500,
) -> list[KnowledgeChunk]:
    """Create compact retrieval summaries without embedding high-volume business rows."""
    entities = {entity.id: entity for entity in graph.entities}
    spans = {span.id: span for span in graph.source_spans}
    sources = {source.id: source for source in graph.sources}
    related: dict[str, list[Assertion]] = defaultdict(list)
    for assertion in graph.assertions:
        related[assertion.subject_id].append(assertion)
        related[assertion.object_id].append(assertion)

    chunks: list[KnowledgeChunk] = []
    structured = [
        entity
        for entity in graph.entities
        if entity_graph_kind(entity) == "data" and not entity.metadata.get("semantic_summary")
    ]
    architecture = [entity for entity in graph.entities if entity_graph_kind(entity) != "data"]

    by_dataset: dict[str, list[Entity]] = defaultdict(list)
    by_domain_type: dict[tuple[str, str], list[Entity]] = defaultdict(list)
    for entity in structured:
        mapped_type = str(entity.metadata.get("mapped_type") or "Record")
        datasets_value = entity.metadata.get("datasets")
        datasets = (
            [str(value) for value in datasets_value]
            if isinstance(datasets_value, list)
            else [str(entity.metadata.get("dataset") or "Structured data")]
        )
        for dataset_value in datasets:
            dataset = str(dataset_value)
            by_dataset[dataset].append(entity)
            by_domain_type[(dataset, mapped_type)].append(entity)

    for dataset, items in sorted(by_dataset.items()):
        chunks.append(_structured_summary_chunk(graph, dataset, items, kind="dataset"))
    for (dataset, mapped_type), items in sorted(by_domain_type.items()):
        chunks.append(
            _structured_summary_chunk(
                graph,
                f"{dataset}: {mapped_type}",
                items,
                kind="domain",
                mapped_type=mapped_type,
            )
        )

    by_source: dict[str, list[Entity]] = defaultdict(list)
    for entity in architecture:
        if entity.source_path and not _is_test_entity(entity):
            by_source[_artifact_path(entity.source_path)].append(entity)
    for source_path, items in sorted(by_source.items()):
        chunks.append(
            _architecture_summary_chunk(
                graph,
                source_path,
                items,
                related=related,
                entities=entities,
            )
        )

    indexed_types = (
        {EntityType(name) for name in entity_types} if entity_types else _DEFAULT_INDEXED_TYPES
    )
    selected = sorted(
        (
            entity
            for entity in architecture
            if entity.type in indexed_types and not _is_test_entity(entity)
        ),
        key=lambda entity: (-len(related.get(entity.id, [])), entity.id),
    )[:entity_limit]
    for entity in selected:
        chunks.append(
            _entity_chunk(
                graph,
                entity,
                assertions=related.get(entity.id, []),
                entities=entities,
                spans=spans,
                sources=sources,
            )
        )

    chunks.extend(
        _document_chunks(graph, entities=entities, spans=spans, limit=document_chunk_limit)
    )

    return sorted({chunk.id: chunk for chunk in chunks}.values(), key=lambda item: item.id)


def _document_chunks(
    graph: ExtractedGraph,
    *,
    entities: dict[str, Entity],
    spans: dict[str, SourceSpan],
    limit: int,
) -> list[KnowledgeChunk]:
    """Full-text retrieval chunks for ingested documents (source_type == 'document')."""
    sources = {source.id: source for source in graph.sources}
    entity_by_path: dict[str, str] = {}
    for entity in entities.values():
        if entity.source_path:
            entity_by_path.setdefault(_artifact_path(entity.source_path), entity.id)
    document_chunks: list[KnowledgeChunk] = []
    for chunk in sorted(graph.chunks, key=lambda item: item.id):
        span = spans.get(chunk.source_span_id)
        source = sources.get(span.source_id) if span else None
        if source is None or source.source_type != "document":
            continue
        path = _artifact_path(source.path)
        anchor = entity_by_path.get(path)
        if anchor is None:
            continue
        document_chunks.append(
            _make_chunk(
                graph,
                title=f"{source.path} · part {chunk.ordinal + 1}",
                kind="document",
                entity_ids=[anchor],
                text=f"Document: {source.path}\n\n{chunk.text}",
                source_span_ids=[chunk.source_span_id],
                source_paths=[path],
                evidence_level="evidence_backed",
            )
        )
    # ponytail: hard cap keeps embedding cost bounded on huge doc sets; raise via
    # rag.document_chunk_limit when a project needs deeper document coverage.
    return document_chunks[:limit]


def _entity_chunk(
    graph: ExtractedGraph,
    entity: Entity,
    *,
    assertions: list[Assertion],
    entities: dict[str, Entity],
    spans: dict[str, SourceSpan],
    sources: dict[str, Source],
) -> KnowledgeChunk:
    assertions = sorted(assertions, key=lambda item: item.id)
    span_ids = {span_id for span_id in entity.source_span_ids if span_id}
    source_paths = {_artifact_path(entity.source_path)} if entity.source_path else set()
    lines = [
        f"Entity: {entity.name}",
        f"Type: {entity.metadata.get('mapped_type') or entity.type.value}",
    ]
    if entity.description:
        lines.append(f"Description: {entity.description}")

    relationship_lines: list[str] = []
    evidence_lines: list[str] = []
    for assertion in assertions[:20]:
        subject = entities.get(assertion.subject_id)
        object_ = entities.get(assertion.object_id)
        if subject is not None and object_ is not None:
            relationship_lines.append(f"{subject.name} {assertion.predicate} {object_.name}")
        if assertion.evidence_span_id:
            span_ids.add(assertion.evidence_span_id)
        if assertion.source_path:
            source_paths.add(_artifact_path(assertion.source_path))
        if assertion.evidence_text:
            evidence_lines.append(_truncate(assertion.evidence_text.strip(), 500))

    for span_id in sorted(span_ids):
        span = spans.get(span_id)
        if span is None:
            continue
        source = sources.get(span.source_id)
        if source is not None:
            source_paths.add(_artifact_path(source.path))
        if span.text.strip() and len(evidence_lines) < 8:
            evidence_lines.append(_truncate(span.text.strip(), 500))

    if relationship_lines:
        lines.append("Relationships:\n- " + "\n- ".join(dict.fromkeys(relationship_lines)))
    if evidence_lines:
        lines.append("Evidence:\n- " + "\n- ".join(dict.fromkeys(evidence_lines)))
    level = _entity_evidence_level(entity, assertions, bool(evidence_lines or source_paths))
    return _make_chunk(
        graph,
        title=entity.name,
        kind="entity",
        entity_ids=[entity.id],
        text="\n".join(lines),
        source_span_ids=sorted(span_ids),
        source_paths=sorted(path for path in source_paths if path),
        evidence_level=level,
    )


def _architecture_summary_chunk(
    graph: ExtractedGraph,
    source_path: str,
    items: list[Entity],
    *,
    related: dict[str, list[Assertion]],
    entities: dict[str, Entity],
) -> KnowledgeChunk:
    primary = sorted(items, key=lambda item: (item.type != EntityType.file, item.id))[0]
    types: dict[str, int] = defaultdict(int)
    names: list[str] = []
    assertions: dict[str, Assertion] = {}
    for entity in items:
        types[entity.type.value] += 1
        names.append(entity.name)
        assertions.update({item.id: item for item in related.get(entity.id, [])})
    lines = [
        f"Architecture source: {source_path}",
        "Contents: " + ", ".join(f"{name} ({count})" for name, count in sorted(types.items())),
        "Named elements: " + ", ".join(names[:40]),
    ]
    relationship_lines = []
    span_ids: set[str] = set()
    for assertion in sorted(assertions.values(), key=lambda item: item.id)[:20]:
        subject = entities.get(assertion.subject_id)
        object_ = entities.get(assertion.object_id)
        if subject and object_:
            relationship_lines.append(f"{subject.name} {assertion.predicate} {object_.name}")
        if assertion.evidence_span_id:
            span_ids.add(assertion.evidence_span_id)
    if relationship_lines:
        lines.append("Relationships:\n- " + "\n- ".join(dict.fromkeys(relationship_lines)))
    return _make_chunk(
        graph,
        title=source_path,
        kind="architecture",
        entity_ids=[primary.id],
        text="\n".join(lines),
        source_span_ids=sorted(span_ids),
        source_paths=[source_path],
        evidence_level="evidence_backed",
    )


def _structured_summary_chunk(
    graph: ExtractedGraph,
    title: str,
    items: list[Entity],
    *,
    kind: str,
    mapped_type: str | None = None,
) -> KnowledgeChunk:
    dataset_name = title.split(": ", 1)[0]
    dataset_paths = {
        _artifact_path(path)
        for item in items
        for path in _dataset_paths(item, dataset_name)
    }
    paths = sorted(path for path in dataset_paths if path)
    datasets = [dataset_name]
    domains = sorted({str(item.metadata.get("domain") or "") for item in items} - {""})
    connectors = sorted({str(item.metadata.get("connector") or "") for item in items} - {""})
    type_counts: dict[str, int] = defaultdict(int)
    representatives: dict[str, Entity] = {}
    for item in items:
        item_type = str(item.metadata.get("mapped_type") or "Record")
        type_counts[item_type] += 1
        representatives.setdefault(item_type, item)
    representative_names = list(
        dict.fromkeys(item.name for item in items if not _is_opaque_name(item.name))
    )[:8]
    lines = [
        f"Structured dataset: {', '.join(datasets) or title}",
        f"Domain: {', '.join(domains) or 'unspecified'}",
        f"Connector: {', '.join(connectors) or 'unknown'}",
        "Source artifacts: " + (", ".join(paths) or "unknown"),
        "Record types: "
        + ", ".join(f"{name} ({count})" for name, count in sorted(type_counts.items())),
    ]
    if representative_names:
        lines.append("Representative names: " + ", ".join(representative_names))
    if mapped_type:
        lines.insert(1, f"Business concept: {mapped_type}")
    return _make_chunk(
        graph,
        title=title,
        kind=kind,
        entity_ids=[item.id for item in representatives.values()][:12],
        text="\n".join(lines),
        source_span_ids=sorted(
            {span_id for item in items for span_id in item.source_span_ids if span_id}
        ),
        source_paths=paths,
        evidence_level="authoritative",
    )


def _make_chunk(
    graph: ExtractedGraph,
    *,
    title: str,
    kind: str,
    entity_ids: list[str],
    text: str,
    source_span_ids: list[str],
    source_paths: list[str],
    evidence_level: str,
) -> KnowledgeChunk:
    text = _truncate(text.strip(), 6000)
    primary_entity_id = entity_ids[0]
    content_hash = stable_hash(
        json.dumps(
            {
                "schema_version": _CHUNK_SCHEMA_VERSION,
                "title": title,
                "kind": kind,
                "entity_ids": entity_ids,
                "text": text,
                "source_span_ids": source_span_ids,
                "source_paths": source_paths,
                "evidence_level": evidence_level,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return KnowledgeChunk(
        id=stable_id("knowledge_chunk", graph.project_slug, kind, title),
        project_slug=graph.project_slug,
        entity_id=primary_entity_id,
        entity_ids=entity_ids,
        title=title,
        kind=kind,
        text=text,
        content_hash=content_hash,
        source_span_ids=source_span_ids,
        source_paths=source_paths,
        evidence_level=evidence_level,
    )


def _dataset_paths(entity: Entity, dataset: str) -> list[str]:
    sources = entity.metadata.get("dataset_sources")
    if isinstance(sources, dict) and dataset in sources:
        paths = sources[dataset]
        if isinstance(paths, list):
            return [str(path) for path in paths]
    return [entity.source_path] if entity.source_path else []


class KnowledgeIndexer:
    def __init__(self, client: GraphClient, embedder: Embedder) -> None:
        self.client = client
        self.embedder = embedder

    def index(
        self,
        chunks: list[KnowledgeChunk],
        *,
        index_name: str,
        dimension: int,
        embedding_model: str,
    ) -> IndexResult:
        if not chunks:
            raise ValueError("Cannot build a GraphRAG index from an empty graph.")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", index_name):
            raise ValueError("Neo4j vector index name must be a safe identifier.")
        if dimension < 1:
            raise ValueError("Embedding dimension must be positive.")

        index_statement = f"""
        CREATE VECTOR INDEX {index_name} IF NOT EXISTS
        FOR (chunk:KnowledgeChunk) ON (chunk.embedding)
        WITH [chunk.project_slug]
        OPTIONS {{indexConfig: {{
          `vector.dimensions`: {dimension},
          `vector.similarity_function`: 'cosine'
        }}}}
        """
        try:
            self.client.execute(index_statement)
        except neo4j.exceptions.ClientError as exc:
            if "SyntaxError" not in exc.code:
                raise
            # Neo4j before 2026.01 has no vector-index filterable-property clause.
            self.client.execute(index_statement.replace("WITH [chunk.project_slug]", ""))
        index_rows = self.client.query(
            """
            SHOW INDEXES YIELD name, type, labelsOrTypes, properties, options
            WHERE name = $index_name
            RETURN type, labelsOrTypes, properties, options
            """,
            {"index_name": index_name},
        )
        if index_rows:
            index_row = index_rows[0]
            if (
                str(index_row.get("type") or "").upper() != "VECTOR"
                or index_row.get("labelsOrTypes") != ["KnowledgeChunk"]
                or index_row.get("properties")
                not in (["embedding"], ["embedding", "project_slug"])
            ):
                raise ValueError("Configured vector index must target KnowledgeChunk.embedding.")
            options = index_row.get("options")
            index_config = options.get("indexConfig", {}) if isinstance(options, dict) else {}
            actual_dimension = index_config.get("vector.dimensions")
            if actual_dimension is not None and int(actual_dimension) != dimension:
                raise ValueError(
                    f"Vector index dimension mismatch: expected {dimension}, "
                    f"found {actual_dimension}."
                )
        project_slug = chunks[0].project_slug
        if any(chunk.project_slug != project_slug for chunk in chunks):
            raise ValueError("All knowledge chunks must belong to one project.")

        rows = self.client.query(
            """
            MATCH (c:KnowledgeChunk {project_slug: $project_slug})
            RETURN c.id AS id, c.content_hash AS content_hash,
                   c.embedding_model AS embedding_model
            """,
            {"project_slug": project_slug},
        )
        existing = {
            str(row["id"]): (
                str(row.get("content_hash") or ""),
                str(row.get("embedding_model") or ""),
            )
            for row in rows
        }
        current_ids = [chunk.id for chunk in chunks]
        changed = [
            chunk
            for chunk in chunks
            if existing.get(chunk.id) != (chunk.content_hash, embedding_model)
        ]

        embedded_rows: list[dict[str, object]] = []
        for chunk_batch in batched(changed, 32):
            batch_chunks = list(chunk_batch)
            if isinstance(self.embedder, BatchEmbedder):
                embeddings = self.embedder.embed_documents(
                    [chunk.text for chunk in batch_chunks]
                )
                if len(embeddings) != len(batch_chunks):
                    raise ValueError("Embedding provider returned an unexpected batch size.")
            else:
                embeddings = [self.embedder.embed_query(chunk.text) for chunk in batch_chunks]
            for chunk, embedding in zip(batch_chunks, embeddings, strict=True):
                if len(embedding) != dimension:
                    raise ValueError(
                        "Embedding dimension mismatch: "
                        f"expected {dimension}, received {len(embedding)}."
                    )
                embedded_rows.append(
                    {
                        **chunk.model_dump(),
                        "embedding_model": embedding_model,
                        "embedding": embedding,
                    }
                )

        for batch in batched(embedded_rows, 100):
            batch_rows = list(batch)
            self.client.execute(
                """
                UNWIND $chunks AS row
                MERGE (chunk:KnowledgeChunk {id: row.id})
                SET chunk.project_slug = row.project_slug,
                    chunk.entity_id = row.entity_id,
                    chunk.entity_ids = row.entity_ids,
                    chunk.title = row.title,
                    chunk.kind = row.kind,
                    chunk.text = row.text,
                    chunk.content_hash = row.content_hash,
                    chunk.source_paths = row.source_paths,
                    chunk.source_span_ids = row.source_span_ids,
                    chunk.evidence_level = row.evidence_level,
                    chunk.embedding_model = row.embedding_model,
                    chunk.embedding = row.embedding,
                    chunk.indexed_at = datetime()
                WITH chunk, row
                OPTIONAL MATCH (chunk)-[old:ABOUT|SUPPORTED_BY]->()
                DELETE old
                WITH chunk, row
                UNWIND range(0, size(row.entity_ids) - 1) AS ordinal
                WITH chunk, row, ordinal, row.entity_ids[ordinal] AS entity_id
                MATCH (entity:Entity {id: entity_id})
                MERGE (chunk)-[about:ABOUT]->(entity)
                SET about.ordinal = ordinal
                """,
                {"chunks": batch_rows},
            )
            if any(row["source_span_ids"] for row in batch_rows):
                self.client.execute(
                    """
                    UNWIND $chunks AS row
                    MATCH (chunk:KnowledgeChunk {id: row.id})
                    UNWIND row.source_span_ids AS span_id
                    MATCH (span:SourceSpan {id: span_id})
                    MERGE (chunk)-[:SUPPORTED_BY]->(span)
                    """,
                    {"chunks": batch_rows},
                )

        stale_ids = sorted(set(existing) - set(current_ids))
        self.client.execute(
            """
            MATCH (stale:KnowledgeChunk {project_slug: $project_slug})
            WHERE NOT stale.id IN $chunk_ids
            DETACH DELETE stale
            """,
            {"project_slug": project_slug, "chunk_ids": current_ids},
        )
        return IndexResult(
            indexed=len(changed),
            unchanged=len(chunks) - len(changed),
            deleted=len(stale_ids),
            total=len(chunks),
        )


def _entity_evidence_level(entity: Entity, assertions: list[Assertion], has_evidence: bool) -> str:
    extraction_sources = {
        entity.extraction_source,
        *(item.extraction_source for item in assertions),
    }
    has_authoritative = "structured_connector" in extraction_sources
    has_extracted = bool(extraction_sources - {"structured_connector"})
    if has_authoritative and has_extracted:
        return "mixed"
    if has_authoritative:
        return "authoritative"
    if has_evidence or entity.graphify_id:
        return "evidence_backed"
    return "weak"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
