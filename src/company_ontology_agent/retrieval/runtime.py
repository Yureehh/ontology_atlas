from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from company_ontology_agent.config.project_config import ProjectConfig, load_project_config
from company_ontology_agent.config.settings import RuntimeSettings, runtime_settings
from company_ontology_agent.graph.neo4j_client import Neo4jClient, Neo4jConnection
from company_ontology_agent.graph.repository import Neo4jGraphRepository
from company_ontology_agent.retrieval.answerer import QueryResponse
from company_ontology_agent.retrieval.graphrag import (
    GraphRAGService,
    Neo4jOpenAIGenerator,
    Neo4jVectorCypherRetriever,
)
from company_ontology_agent.retrieval.indexing import (
    Embedder,
    IndexResult,
    KnowledgeIndexer,
    build_knowledge_chunks,
)


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


def index_project(project_root: Path) -> IndexResult:
    config = load_project_config(project_root)
    settings = runtime_settings(config)
    _validate(config, settings, require_llm=False)
    client = _client(config, settings)
    try:
        graph = Neo4jGraphRepository(client).read_graph(config.project_slug)
        chunks = build_knowledge_chunks(
            graph,
            wiki_root=project_root / config.wiki.output_path,
            wiki_output_path=config.wiki.output_path,
        )
        embedder = _embedder(config, settings)
        embedding_model = _required(settings.embedding_model, config.embedding.model_env)
        result = KnowledgeIndexer(client, embedder).index(
            chunks,
            index_name=config.graph.vector_index_name,
            dimension=config.embedding.dimension,
            embedding_model=embedding_model,
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
    config = load_project_config(project_root)
    settings = runtime_settings(config)
    _validate(config, settings, require_llm=True)
    client = _client(config, settings)
    try:
        service = GraphRAGService(
            Neo4jVectorCypherRetriever(
                client.driver,
                index_name=config.graph.vector_index_name,
                embedder=_embedder(config, settings),
                database=settings.neo4j_database,
                max_hops=config.rag.max_hops,
            ),
            Neo4jOpenAIGenerator(
                model_name=_required(settings.llm_model, config.llm.model_env),
                api_key=settings.llm_api_key,
            ),
        )
        return service.ask(
            question,
            project_slug=config.project_slug,
            top_k=config.rag.top_k,
        )
    finally:
        client.close()


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
            count_rows = client.query(
                """
                MATCH (c:KnowledgeChunk {project_slug: $project_slug})
                RETURN count(c) AS chunk_count
                """,
                {"project_slug": config.project_slug},
            )
            index_rows = client.query(
                "SHOW INDEXES YIELD name, state WHERE name = $index_name RETURN state",
                {"index_name": index_name},
            )
        finally:
            client.close()
    except Exception as exc:
        return RagStatus(
            ready=False,
            enabled=True,
            index_name=index_name,
            message=str(exc),
        )
    count = int(str(count_rows[0].get("chunk_count", 0))) if count_rows else 0
    online = bool(index_rows and str(index_rows[0].get("state")) == "ONLINE")
    ready = count > 0 and online
    return RagStatus(
        ready=ready,
        enabled=True,
        chunk_count=count,
        index_name=index_name,
        message=(
            "GraphRAG is ready."
            if ready
            else "GraphRAG has no online populated index. Run ontology-agent rag index."
        ),
    )


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
    return OpenAIEmbeddings(
        model=_required(settings.embedding_model, config.embedding.model_env),
        api_key=settings.llm_api_key,
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
