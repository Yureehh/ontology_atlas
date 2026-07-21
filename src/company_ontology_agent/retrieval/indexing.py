from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from company_ontology_agent.graph.models import Assertion, Entity, EntityType, ExtractedGraph
from company_ontology_agent.utils.hashing import stable_hash
from company_ontology_agent.utils.ids import stable_id
from company_ontology_agent.wiki.templates import TYPE_DIRS, entity_filename


class KnowledgeChunk(BaseModel):
    id: str
    project_slug: str
    entity_id: str
    text: str
    content_hash: str
    source_span_ids: list[str] = Field(default_factory=list)
    source_paths: list[str] = Field(default_factory=list)
    wiki_path: str
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


def build_knowledge_chunks(
    graph: ExtractedGraph,
    *,
    wiki_root: Path | None = None,
    wiki_output_path: str = "wiki",
) -> list[KnowledgeChunk]:
    """Create one compact, traceable retrieval document per canonical entity."""
    entities = {entity.id: entity for entity in graph.entities}
    spans = {span.id: span for span in graph.source_spans}
    sources = {source.id: source for source in graph.sources}
    related: dict[str, list[Assertion]] = defaultdict(list)
    for assertion in graph.assertions:
        related[assertion.subject_id].append(assertion)
        related[assertion.object_id].append(assertion)

    chunks: list[KnowledgeChunk] = []
    for entity in sorted(graph.entities, key=lambda item: item.id):
        assertions = sorted(related.get(entity.id, []), key=lambda item: item.id)
        span_ids = {span_id for span_id in entity.source_span_ids if span_id}
        source_paths = {entity.source_path} if entity.source_path else set()
        lines = [
            f"Entity: {entity.name}",
            f"Type: {entity.metadata.get('mapped_type') or entity.type.value}",
        ]
        if entity.description:
            lines.append(f"Description: {entity.description}")

        relationship_lines: list[str] = []
        evidence_lines: list[str] = []
        for assertion in assertions[:60]:
            subject = entities.get(assertion.subject_id)
            object_ = entities.get(assertion.object_id)
            if subject is not None and object_ is not None:
                relationship_lines.append(f"{subject.name} {assertion.predicate} {object_.name}")
            if assertion.evidence_span_id:
                span_ids.add(assertion.evidence_span_id)
            if assertion.source_path:
                source_paths.add(assertion.source_path)
            if assertion.evidence_text:
                evidence_lines.append(_truncate(assertion.evidence_text.strip(), 1000))

        for span_id in sorted(span_ids):
            span = spans.get(span_id)
            if span is None:
                continue
            source = sources.get(span.source_id)
            if source is not None:
                source_paths.add(source.path)
            if span.text.strip():
                evidence_lines.append(_truncate(span.text.strip(), 1000))

        if relationship_lines:
            lines.append("Relationships:\n- " + "\n- ".join(dict.fromkeys(relationship_lines)))
        if evidence_lines:
            lines.append("Evidence:\n- " + "\n- ".join(dict.fromkeys(evidence_lines)))

        wiki_path, wiki_context = _entity_wiki_context(
            entity,
            wiki_root=wiki_root,
            wiki_output_path=wiki_output_path,
        )
        if wiki_context:
            lines.append(f"Generated wiki context:\n{wiki_context}")

        text = _truncate("\n".join(lines).strip(), 24000)
        level = _entity_evidence_level(entity, assertions, bool(evidence_lines or source_paths))
        sorted_span_ids = sorted(span_ids)
        sorted_source_paths = sorted(path for path in source_paths if path)
        content_hash = stable_hash(
            json.dumps(
                {
                    "text": text,
                    "source_span_ids": sorted_span_ids,
                    "source_paths": sorted_source_paths,
                    "wiki_path": wiki_path,
                    "evidence_level": level,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        chunks.append(
            KnowledgeChunk(
                id=stable_id("knowledge_chunk", graph.project_slug, entity.id),
                project_slug=graph.project_slug,
                entity_id=entity.id,
                text=text,
                content_hash=content_hash,
                source_span_ids=sorted_span_ids,
                source_paths=sorted_source_paths,
                wiki_path=wiki_path,
                evidence_level=level,
            )
        )
    return chunks


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

        self.client.execute(
            f"""
            CREATE VECTOR INDEX {index_name} IF NOT EXISTS
            FOR (chunk:KnowledgeChunk) ON (chunk.embedding)
            OPTIONS {{indexConfig: {{
              `vector.dimensions`: {dimension},
              `vector.similarity_function`: 'cosine'
            }}}}
            """
        )
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
                or index_row.get("properties") != ["embedding"]
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

        for chunk in changed:
            embedding = self.embedder.embed_query(chunk.text)
            if len(embedding) != dimension:
                raise ValueError(
                    "Embedding dimension mismatch: "
                    f"expected {dimension}, received {len(embedding)}."
                )
            self.client.execute(
                """
                MERGE (chunk:KnowledgeChunk {id: $id})
                SET chunk.project_slug = $project_slug,
                    chunk.entity_id = $entity_id,
                    chunk.text = $text,
                    chunk.content_hash = $content_hash,
                    chunk.source_paths = $source_paths,
                    chunk.source_span_ids = $source_span_ids,
                    chunk.wiki_path = $wiki_path,
                    chunk.evidence_level = $evidence_level,
                    chunk.embedding_model = $embedding_model,
                    chunk.embedding = $embedding,
                    chunk.indexed_at = datetime()
                WITH chunk
                OPTIONAL MATCH (chunk)-[old:ABOUT|SUPPORTED_BY]->()
                DELETE old
                WITH chunk
                MATCH (entity:Entity {id: $entity_id})
                MERGE (chunk)-[:ABOUT]->(entity)
                """,
                {
                    **chunk.model_dump(),
                    "embedding_model": embedding_model,
                    "embedding": embedding,
                },
            )
            if chunk.source_span_ids:
                self.client.execute(
                    """
                    MATCH (chunk:KnowledgeChunk {id: $id})
                    UNWIND $source_span_ids AS span_id
                    MATCH (span:SourceSpan {id: span_id})
                    MERGE (chunk)-[:SUPPORTED_BY]->(span)
                    """,
                    {"id": chunk.id, "source_span_ids": chunk.source_span_ids},
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


def _entity_wiki_context(
    entity: Entity,
    *,
    wiki_root: Path | None,
    wiki_output_path: str,
) -> tuple[str, str]:
    directory = {
        EntityType.module: "modules",
        EntityType.api_endpoint: "apis",
    }.get(entity.type, TYPE_DIRS.get(entity.type, "entities"))
    filename = entity_filename(entity)
    output_path = Path(wiki_output_path).as_posix().removeprefix("./").rstrip("/") or "wiki"
    stored_path = f"{output_path}/{directory}/{filename}"
    if wiki_root is None:
        return stored_path, ""
    try:
        context = (wiki_root / directory / filename).read_text(encoding="utf-8").strip()
    except OSError:
        return stored_path, ""
    return stored_path, _truncate(context, 6000)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
