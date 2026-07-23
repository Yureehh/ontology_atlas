from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from company_ontology_agent.config.project_config import ProjectConfig, load_project_config
from company_ontology_agent.config.settings import RuntimeSettings, runtime_settings
from company_ontology_agent.graph.neo4j_client import Neo4jClient, Neo4jConnection
from company_ontology_agent.graph.repository import Neo4jGraphRepository
from company_ontology_agent.retrieval.analytics import Neo4jAnalyticalEngine
from company_ontology_agent.retrieval.answer_composition import GraphRAGService
from company_ontology_agent.retrieval.answerer import QueryResponse
from company_ontology_agent.retrieval.graphrag import (
    Neo4jOpenAIGenerator,
    Neo4jVectorCypherRetriever,
)
from company_ontology_agent.retrieval.indexing import (
    Embedder,
    IndexResult,
    KnowledgeIndexer,
    build_knowledge_chunks,
)
from company_ontology_agent.retrieval.text2cypher import SafeText2CypherEngine


class RagIndexStatus(BaseModel):
    indexed_at: str
    embedding_model: str
    indexed: int
    unchanged: int
    deleted: int
    total: int


class RagStatus(BaseModel):
    ready: bool
    enabled: bool
    chunk_count: int = 0
    index_name: str
    message: str
    stale: bool = False


GraphLayer = Literal["all", "repo", "data"]


class ProjectRagRuntime:
    """Long-lived GraphRAG resources shared by every request from one portal server."""

    def __init__(
        self,
        *,
        config: ProjectConfig,
        client: Neo4jClient,
        service: GraphRAGService,
    ) -> None:
        self.config = config
        self.client = client
        self.service = service

    def ask(self, question: str) -> QueryResponse:
        return self.service.ask(
            question,
            project_slug=self.config.project_slug,
            top_k=self.config.rag.top_k,
        )

    def status(self) -> RagStatus:
        return _status_with_client(self.config, self.client)

    def search_entities(
        self, query: str, *, layer: GraphLayer = "all", limit: int = 25
    ) -> list[dict[str, object]]:
        rows = self.client.query(
            """
            MATCH (:Project {slug: $project_slug})-[:HAS_ENTITY]->(entity:Entity)
            WHERE coalesce(entity.stale, false) = false
              AND (toLower(entity.name) CONTAINS $query
                   OR entity.normalized_name CONTAINS $query
                   OR any(alias IN coalesce(entity.aliases, [])
                          WHERE toLower(alias) CONTAINS $query))
              AND ($layer = 'all'
                   OR ($layer = 'data'
                       AND entity.extraction_source = 'structured_connector')
                   OR ($layer = 'repo'
                       AND entity.extraction_source <> 'structured_connector'))
            RETURN entity.id AS id, entity.name AS name,
                   coalesce(entity.mapped_type, entity.type, labels(entity)[0]) AS type,
                   CASE WHEN entity.extraction_source = 'structured_connector'
                        THEN 'data' ELSE 'repo' END AS layer
            ORDER BY CASE WHEN toLower(entity.name) = $query THEN 0
                          WHEN toLower(entity.name) STARTS WITH $query THEN 1 ELSE 2 END,
                     size(entity.name), entity.name
            LIMIT $limit
            """,
            {
                "project_slug": self.config.project_slug,
                "query": query.casefold(),
                "layer": layer,
                "limit": max(1, min(50, limit)),
            },
        )
        return [
            {
                "i": str(row.get("id") or ""),
                "n": str(row.get("name") or ""),
                "t": str(row.get("type") or "Entity"),
                "layer": str(row.get("layer") or "repo"),
            }
            for row in rows
        ]

    def list_sources(self, *, limit: int = 500) -> list[dict[str, object]]:
        rows = self.client.query(
            """
            MATCH (:Project {slug: $slug})-[:HAS_SOURCE]->(s:Source)
            OPTIONAL MATCH (s)-[:HAS_SPAN]->(ss:SourceSpan)
            OPTIONAL MATCH (c:Chunk)-[:DERIVED_FROM]->(ss)
            RETURN s.id AS id, s.path AS path, s.source_type AS source_type,
                   s.title AS title, count(DISTINCT ss) AS span_count,
                   count(DISTINCT c) AS chunk_count
            ORDER BY s.path
            LIMIT $limit
            """,
            {"slug": self.config.project_slug, "limit": max(1, min(2000, limit))},
        )
        return [
            {
                "id": str(row.get("id") or ""),
                "path": str(row.get("path") or ""),
                "source_type": str(row.get("source_type") or ""),
                "title": str(row.get("title") or ""),
                "span_count": int(str(row.get("span_count") or 0)),
                "chunk_count": int(str(row.get("chunk_count") or 0)),
            }
            for row in rows
        ]

    def source_chunks(self, source_id: str, *, limit: int = 500) -> list[dict[str, object]]:
        rows = self.client.query(
            """
            MATCH (:Project {slug: $slug})-[:HAS_SOURCE]->
                  (s:Source {id: $source_id})-[:HAS_SPAN]->(ss:SourceSpan)
            OPTIONAL MATCH (c:Chunk)-[:DERIVED_FROM]->(ss)
            RETURN ss.id AS span_id, ss.start AS start, ss.end AS end,
                   coalesce(c.text, ss.text) AS text, coalesce(c.ordinal, 0) AS ordinal
            ORDER BY ordinal, start, span_id
            LIMIT $limit
            """,
            {
                "slug": self.config.project_slug,
                "source_id": source_id,
                "limit": max(1, min(2000, limit)),
            },
        )
        return [
            {
                "span_id": str(row.get("span_id") or ""),
                "start": int(str(row.get("start") or 0)),
                "end": int(str(row.get("end") or 0)),
                "text": str(row.get("text") or ""),
                "ordinal": int(str(row.get("ordinal") or 0)),
            }
            for row in rows
        ]

    def close(self) -> None:
        self.client.close()


def index_project(project_root: Path) -> IndexResult:
    config = load_project_config(project_root)
    settings = runtime_settings(config)
    _validate(config, settings, require_llm=False)
    client = _client(config, settings)
    try:
        graph = Neo4jGraphRepository(client).read_graph(config.project_slug)
        chunks = build_knowledge_chunks(
            graph,
            entity_limit=config.rag.entity_chunk_limit,
            entity_types=config.rag.entity_chunk_types,
            document_chunk_limit=config.rag.document_chunk_limit,
        )
        embedder = _embedder(config, settings)
        embedding_model = _required(settings.embedding_model, config.embedding.model_env)
        result = KnowledgeIndexer(client, embedder).index(
            chunks,
            index_name=config.graph.vector_index_name,
            dimension=config.embedding.dimension,
            embedding_model=embedding_model,
        )
        # Fingerprint the graph the index was built from so `rag status` can flag staleness.
        client.execute(
            """
            MERGE (m:RagIndexMeta {project_slug: $slug})
            SET m.entity_count = $entity_count,
                m.assertion_count = $assertion_count,
                m.indexed_at = $indexed_at,
                m.embedding_model = $embedding_model
            """,
            {
                "slug": config.project_slug,
                "entity_count": len(graph.entities),
                "assertion_count": len(graph.assertions),
                "indexed_at": datetime.now(UTC).isoformat(),
                "embedding_model": embedding_model,
            },
        )
        status_path = project_root / "rag" / "index-status.json"
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(
            RagIndexStatus(
                indexed_at=datetime.now(UTC).isoformat(),
                embedding_model=embedding_model,
                indexed=result.indexed,
                unchanged=result.unchanged,
                deleted=result.deleted,
                total=result.total,
            ).model_dump_json(indent=2),
            encoding="utf-8",
        )
        return result
    finally:
        client.close()


def ask_project(project_root: Path, question: str) -> QueryResponse:
    runtime = create_rag_runtime(project_root)
    try:
        return runtime.ask(question)
    finally:
        runtime.close()


def create_rag_runtime(
    project_root: Path, *, allow_text2cypher: bool = False
) -> ProjectRagRuntime:
    config = load_project_config(project_root)
    settings = runtime_settings(config)
    _validate(config, settings, require_llm=True)
    client = _client(config, settings)
    try:
        embedder = _embedder(config, settings)
        generator = Neo4jOpenAIGenerator(
            model_name=_required(settings.llm_model, config.llm.model_env),
            api_key=settings.llm_api_key,
        )
        retriever = Neo4jVectorCypherRetriever(
            client.driver,
            index_name=config.graph.vector_index_name,
            embedder=embedder,
            database=settings.neo4j_database,
            max_hops=config.rag.max_hops,
        )
        analytics = (
            Neo4jAnalyticalEngine(
                client.driver,
                database=settings.neo4j_database,
                max_hops=config.rag.analytics.max_hops,
                max_rows=config.rag.analytics.max_rows,
                timeout_seconds=config.rag.analytics.timeout_seconds,
            )
            if config.rag.analytics.enabled
            else None
        )
        expert = (
            SafeText2CypherEngine(
                client.driver,
                generator.llm,
                database=settings.neo4j_database,
                project_slug=config.project_slug,
                max_hops=config.rag.analytics.max_hops,
                max_rows=config.rag.analytics.max_rows,
                timeout_seconds=config.rag.analytics.timeout_seconds,
                diagnostics_path=project_root / "rag" / "text2cypher-diagnostics.jsonl",
            )
            if allow_text2cypher
            and config.rag.analytics.enabled
            and config.rag.analytics.text2cypher_local
            else None
        )
        service = GraphRAGService(
            retriever,
            generator,
            analytics,
            expert,
        )
    except Exception:
        client.close()
        raise
    return ProjectRagRuntime(
        config=config,
        client=client,
        service=service,
    )


def get_rag_status(project_root: Path) -> RagStatus:
    config = load_project_config(project_root)
    settings = runtime_settings(config)
    index_name = config.graph.vector_index_name
    if not config.rag.enabled:
        return RagStatus(
            ready=False,
            enabled=False,
            index_name=index_name,
            message="GraphRAG is disabled in project.yaml.",
        )
    try:
        _validate(config, settings, require_llm=True)
        client = _client(config, settings)
        try:
            return _status_with_client(config, client)
        finally:
            client.close()
    except Exception as exc:
        return RagStatus(
            ready=False,
            enabled=True,
            index_name=index_name,
            message=str(exc),
        )


def _status_with_client(config: ProjectConfig, client: Neo4jClient) -> RagStatus:
    count_rows = client.query(
        """
        MATCH (c:KnowledgeChunk {project_slug: $project_slug})
        RETURN count(c) AS chunk_count
        """,
        {"project_slug": config.project_slug},
    )
    index_rows = client.query(
        "SHOW INDEXES YIELD name, state WHERE name = $index_name RETURN state",
        {"index_name": config.graph.vector_index_name},
    )
    count = int(str(count_rows[0].get("chunk_count", 0))) if count_rows else 0
    online = bool(index_rows and str(index_rows[0].get("state")) == "ONLINE")
    ready = count > 0 and online
    stale = ready and _index_is_stale(config, client)
    if not ready:
        message = "GraphRAG has no online populated index. Run ontology-agent rag index."
    elif stale:
        message = (
            "GraphRAG is ready, but the graph changed after the last index run. "
            "Run ontology-agent rag index to refresh."
        )
    else:
        message = "GraphRAG is ready."
    return RagStatus(
        ready=ready,
        enabled=True,
        chunk_count=count,
        index_name=config.graph.vector_index_name,
        message=message,
        stale=stale,
    )


def _index_is_stale(config: ProjectConfig, client: Neo4jClient) -> bool:
    rows = client.query(
        """
        OPTIONAL MATCH (m:RagIndexMeta {project_slug: $slug})
        OPTIONAL MATCH (:Project {slug: $slug})-[:HAS_ENTITY]->(e:Entity)
        WITH m, count(e) AS entity_count
        OPTIONAL MATCH (:Project {slug: $slug})-[:HAS_ASSERTION]->(a:Assertion)
        RETURN m.entity_count AS indexed_entities,
               m.assertion_count AS indexed_assertions,
               entity_count, count(a) AS assertion_count
        """,
        {"slug": config.project_slug},
    )
    if not rows:
        return False
    row = rows[0]
    indexed_entities = row.get("indexed_entities")
    indexed_assertions = row.get("indexed_assertions")
    if indexed_entities is None or indexed_assertions is None:
        # Pre-fingerprint index: cannot tell, do not alarm.
        return False
    return int(str(indexed_entities)) != int(str(row.get("entity_count") or 0)) or int(
        str(indexed_assertions)
    ) != int(str(row.get("assertion_count") or 0))


def _client(config: ProjectConfig, settings: RuntimeSettings) -> Neo4jClient:
    return Neo4jClient(
        Neo4jConnection(
            uri=settings.neo4j_uri,
            username=_required(settings.neo4j_user, config.graph.username_env),
            password=_required(settings.neo4j_password, config.graph.password_env),
            database=settings.neo4j_database,
        )
    )


def _embedder(config: ProjectConfig, settings: RuntimeSettings) -> Embedder:
    try:
        from neo4j_graphrag.embeddings import OpenAIEmbeddings
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "GraphRAG dependencies are not installed. Install company-ontology-agent[rag]."
        ) from exc

    class BatchedOpenAIEmbeddings(OpenAIEmbeddings):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            response = self.client.embeddings.create(input=texts, model=self.model)
            return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]

    return BatchedOpenAIEmbeddings(
        model=_required(settings.embedding_model, config.embedding.model_env),
        api_key=settings.llm_api_key,
        timeout=45.0,
        max_retries=1,
    )


def _validate(config: ProjectConfig, settings: RuntimeSettings, *, require_llm: bool) -> None:
    if not config.rag.enabled:
        raise RuntimeError("GraphRAG is disabled. Set rag.enabled: true in project.yaml.")
    if config.embedding.provider != "openai":
        raise RuntimeError("GraphRAG v1 requires embedding.provider: openai.")
    _required(settings.embedding_model, config.embedding.model_env)
    _required(settings.llm_api_key, config.llm.api_key_env)
    _required(settings.neo4j_user, config.graph.username_env)
    _required(settings.neo4j_password, config.graph.password_env)
    if require_llm:
        if config.llm.provider != "openai":
            raise RuntimeError("GraphRAG v1 requires llm.provider: openai.")
        _required(settings.llm_model, config.llm.model_env)


def _required(value: str | None, env_name: str) -> str:
    if not value:
        raise RuntimeError(f"Required setting is missing: {env_name}.")
    return value
