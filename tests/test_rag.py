from __future__ import annotations

import os
import shutil

import pytest
from typer.testing import CliRunner

from company_ontology_agent.api.app import create_app
from company_ontology_agent.cli.main import app
from company_ontology_agent.config.project_config import default_config
from company_ontology_agent.graph.models import (
    Assertion,
    Entity,
    EntityType,
    ExtractedGraph,
    Source,
    SourceSpan,
)
from company_ontology_agent.graph.neo4j_client import Neo4jClient, Neo4jConnection
from company_ontology_agent.graph.repository import Neo4jGraphRepository
from company_ontology_agent.retrieval.answerer import Citation, QueryResponse
from company_ontology_agent.retrieval.evaluation import GoldenQuestion, evaluate_questions
from company_ontology_agent.retrieval.graphrag import (
    GraphRAGService,
    Neo4jVectorCypherRetriever,
    RetrievedContext,
)
from company_ontology_agent.retrieval.indexing import KnowledgeIndexer, build_knowledge_chunks
from company_ontology_agent.retrieval.runtime import RagStatus


def _graph() -> ExtractedGraph:
    return ExtractedGraph(
        project_slug="customer-platform",
        sources=[
            Source(
                id="source-1",
                path="docs/customer.md",
                source_type="markdown",
                sha256="x",
                title="Customer",
            ),
        ],
        source_spans=[
            SourceSpan(
                id="span-1", source_id="source-1", text="Billing depends on Customer Profile."
            ),
        ],
        entities=[
            Entity(
                id="customer",
                type=EntityType.data_model,
                name="Customer Profile",
                normalized_name="customer profile",
                source_span_ids=["span-1"],
            ),
            Entity(id="billing", type=EntityType.system, name="Billing", normalized_name="billing"),
        ],
        assertions=[
            Assertion(
                id="assertion-1",
                predicate="depends_on",
                subject_id="billing",
                object_id="customer",
                evidence_span_id="span-1",
                confidence=1.0,
                extractor="structured",
                extraction_source="structured_connector",
                source_path="docs/customer.md",
                evidence_text="Billing depends on Customer Profile.",
            )
        ],
    )


def test_rag_config_defaults_are_disabled_and_bounded() -> None:
    config = default_config("demo")
    assert config.rag.enabled is False
    assert config.rag.top_k == 8
    assert config.rag.max_hops == 2


def test_build_knowledge_chunks_is_deterministic_and_traceable() -> None:
    first = build_knowledge_chunks(_graph())
    second = build_knowledge_chunks(_graph())

    assert first == second
    customer = next(chunk for chunk in first if chunk.entity_id == "customer")
    assert customer.evidence_level == "mixed"
    assert customer.source_paths == ["docs/customer.md"]
    assert customer.source_span_ids == ["span-1"]
    assert "Billing depends_on Customer Profile" in customer.text
    assert customer.wiki_path == "wiki/entities/customer-profile.md"


def test_build_knowledge_chunks_uses_specialized_wiki_pages() -> None:
    graph = _graph().model_copy(
        update={
            "entities": [
                Entity(
                    id="module",
                    type=EntityType.module,
                    name="Billing Core",
                    normalized_name="billing core",
                ),
                Entity(
                    id="api",
                    type=EntityType.api_endpoint,
                    name="GET /customers",
                    normalized_name="get customers",
                ),
            ],
            "assertions": [],
        }
    )

    chunks = {chunk.entity_id: chunk for chunk in build_knowledge_chunks(graph)}

    assert chunks["module"].wiki_path == "wiki/modules/billing-core.md"
    assert chunks["api"].wiki_path == "wiki/apis/get-customers.md"


def test_build_knowledge_chunks_includes_generated_wiki_context(tmp_path) -> None:
    wiki_root = tmp_path / "knowledge"
    page = wiki_root / "entities" / "customer-profile.md"
    page.parent.mkdir(parents=True)
    page.write_text("# Customer Profile\n\nCurated ownership and impact context.", encoding="utf-8")

    chunks = build_knowledge_chunks(
        _graph(),
        wiki_root=wiki_root,
        wiki_output_path="knowledge",
    )
    customer = next(chunk for chunk in chunks if chunk.entity_id == "customer")

    assert customer.wiki_path == "knowledge/entities/customer-profile.md"
    assert "Generated wiki context" in customer.text
    assert "Curated ownership and impact context" in customer.text


def test_knowledge_chunk_hash_covers_traceability_metadata() -> None:
    original = build_knowledge_chunks(_graph())
    changed_graph = _graph().model_copy(deep=True)
    changed_graph.entities[0].source_path = "docs/renamed-customer.md"

    changed = build_knowledge_chunks(changed_graph)

    original_customer = next(chunk for chunk in original if chunk.entity_id == "customer")
    changed_customer = next(chunk for chunk in changed if chunk.entity_id == "customer")
    assert original_customer.text == changed_customer.text
    assert original_customer.content_hash != changed_customer.content_hash


class FakeClient:
    def __init__(
        self,
        existing: list[dict[str, object]] | None = None,
        index_dimension: int | None = None,
        index_target: tuple[str, list[str], list[str]] = (
            "VECTOR",
            ["KnowledgeChunk"],
            ["embedding"],
        ),
    ) -> None:
        self.existing = existing or []
        self.index_dimension = index_dimension
        self.index_target = index_target
        self.calls: list[tuple[str, dict[str, object]]] = []

    def query(
        self, statement: str, parameters: dict[str, object] | None = None
    ) -> list[dict[str, object]]:
        self.calls.append((statement, parameters or {}))
        if "RETURN c.id AS id" in statement:
            return self.existing
        if "SHOW INDEXES" in statement and self.index_dimension is not None:
            index_type, labels, properties = self.index_target
            return [
                {
                    "type": index_type,
                    "labelsOrTypes": labels,
                    "properties": properties,
                    "options": {"indexConfig": {"vector.dimensions": self.index_dimension}},
                }
            ]
        return []

    def execute(self, statement: str, parameters: dict[str, object] | None = None) -> None:
        self.calls.append((statement, parameters or {}))


class FakeEmbedder:
    def __init__(self, dimension: int = 3) -> None:
        self.dimension = dimension
        self.texts: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.texts.append(text)
        return [0.1] * self.dimension


def test_indexer_embeds_only_changed_chunks_and_deletes_stale() -> None:
    chunks = build_knowledge_chunks(_graph())
    unchanged = chunks[0]
    client = FakeClient(
        existing=[
            {
                "id": unchanged.id,
                "content_hash": unchanged.content_hash,
                "embedding_model": "test-embedding",
            },
            {"id": "knowledge_chunk_stale", "content_hash": "old"},
        ]
    )
    embedder = FakeEmbedder()

    result = KnowledgeIndexer(client, embedder).index(
        chunks,
        index_name="chunk_embeddings",
        dimension=3,
        embedding_model="test-embedding",
    )

    assert result.indexed == 1
    assert result.unchanged == 1
    assert result.deleted == 1
    assert len(embedder.texts) == 1
    statements = "\n".join(statement for statement, _ in client.calls)
    assert "CREATE VECTOR INDEX chunk_embeddings IF NOT EXISTS" in statements
    assert "MERGE (chunk:KnowledgeChunk" in statements
    assert "DETACH DELETE stale" in statements


def test_indexer_rejects_embedding_dimension_mismatch() -> None:
    client = FakeClient()
    with pytest.raises(ValueError, match="dimension"):
        KnowledgeIndexer(client, FakeEmbedder(dimension=2)).index(
            build_knowledge_chunks(_graph()),
            index_name="chunk_embeddings",
            dimension=3,
            embedding_model="test-embedding",
        )


def test_indexer_rejects_existing_vector_index_dimension_mismatch() -> None:
    with pytest.raises(ValueError, match="Vector index dimension mismatch"):
        KnowledgeIndexer(FakeClient(index_dimension=1536), FakeEmbedder(dimension=3072)).index(
            build_knowledge_chunks(_graph()),
            index_name="chunk_embeddings",
            dimension=3072,
            embedding_model="test-embedding",
        )


def test_indexer_rejects_existing_index_on_wrong_target() -> None:
    client = FakeClient(
        index_dimension=3,
        index_target=("VECTOR", ["Chunk"], ["embedding"]),
    )
    with pytest.raises(ValueError, match="KnowledgeChunk.embedding"):
        KnowledgeIndexer(client, FakeEmbedder()).index(
            build_knowledge_chunks(_graph()),
            index_name="chunk_embeddings",
            dimension=3,
            embedding_model="test-embedding",
        )


def test_indexer_reembeds_when_model_changes() -> None:
    chunks = build_knowledge_chunks(_graph())
    client = FakeClient(
        existing=[
            {
                "id": chunk.id,
                "content_hash": chunk.content_hash,
                "embedding_model": "old-model",
            }
            for chunk in chunks
        ]
    )
    embedder = FakeEmbedder()
    result = KnowledgeIndexer(client, embedder).index(
        chunks,
        index_name="chunk_embeddings",
        dimension=3,
        embedding_model="new-model",
    )
    assert result.indexed == len(chunks)


def test_indexer_rejects_unsafe_index_name() -> None:
    with pytest.raises(ValueError, match="index name"):
        KnowledgeIndexer(FakeClient(), FakeEmbedder()).index(
            build_knowledge_chunks(_graph()),
            index_name="chunk embeddings; DROP INDEX",
            dimension=3,
            embedding_model="test-embedding",
        )


class FakeRetriever:
    def __init__(self, contexts: list[RetrievedContext]) -> None:
        self.contexts = contexts
        self.calls: list[tuple[str, str, int]] = []

    def retrieve(self, question: str, *, project_slug: str, top_k: int) -> list[RetrievedContext]:
        self.calls.append((question, project_slug, top_k))
        return self.contexts


class FakeGenerator:
    def __init__(self, answer: str = "Billing is affected [1].") -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answer


def test_graphrag_service_returns_citations_entities_and_paths() -> None:
    retriever = FakeRetriever(
        [
            RetrievedContext(
                chunk_id="chunk-1",
                text="Billing depends on Customer Profile.",
                entity_id="billing",
                entity_name="Billing",
                entity_type="System",
                source_paths=["docs/customer.md"],
                evidence_level="authoritative",
                score=0.94,
                paths=["Billing -[depends_on]-> Customer Profile"],
                source_span_ids=["span-1"],
                assertion_ids=["assertion-1"],
            )
        ]
    )
    generator = FakeGenerator()

    response = GraphRAGService(retriever, generator).ask(
        "What is affected?", project_slug="customer-platform", top_k=8
    )

    assert response.answer == "Billing is affected [1]."
    assert response.citations[0].source_path == "docs/customer.md"
    assert response.citations[0].evidence_level == "authoritative"
    assert response.entities[0]["name"] == "Billing"
    assert response.paths == [{"summary": "Billing -[depends_on]-> Customer Profile"}]
    assert response.citations[0].source_span_ids == ["span-1"]
    assert response.supporting_assertions == [{"id": "assertion-1"}]
    assert response.trace_id
    assert retriever.calls == [("What is affected?", "customer-platform", 8)]
    assert "untrusted evidence" in generator.prompts[0].lower()


def test_graphrag_service_refuses_when_no_context_is_found() -> None:
    generator = FakeGenerator()
    response = GraphRAGService(FakeRetriever([]), generator).ask(
        "Unknown question", project_slug="customer-platform", top_k=8
    )
    assert "enough project evidence" in response.answer
    assert response.citations == []
    assert response.warnings == ["No matching Neo4j GraphRAG context found."]
    assert generator.prompts == []


def test_graphrag_service_discards_context_when_model_refuses() -> None:
    context = RetrievedContext(
        chunk_id="chunk-1",
        text="Related words without an answer.",
        entity_id="entity",
        entity_name="Entity",
        entity_type="Concept",
        source_paths=["docs/context.md"],
    )
    response = GraphRAGService(
        FakeRetriever([context]), FakeGenerator("INSUFFICIENT_EVIDENCE")
    ).ask("Unsupported question", project_slug="customer-platform", top_k=8)

    assert "enough project evidence" in response.answer
    assert response.citations == []
    assert response.entities == []
    assert response.paths == []
    assert response.warnings == ["Retrieved context did not support an answer."]


def test_official_retriever_uses_fixed_bounded_project_filtered_cypher(monkeypatch) -> None:
    pytest.importorskip("neo4j_graphrag")

    class FakeVectorCypherRetriever:
        instance = None

        def __init__(self, driver, **kwargs):
            self.kwargs = kwargs
            self.search_kwargs = None
            FakeVectorCypherRetriever.instance = self

        def search(self, **kwargs):
            self.search_kwargs = kwargs
            return type(
                "Result",
                (),
                {
                    "items": [
                        type(
                            "Item",
                            (),
                            {
                                "content": (
                                    '{"chunk_id":"chunk","text":"evidence",'
                                    '"entity_id":"entity","entity_name":"Entity",'
                                    '"entity_type":"System"}'
                                )
                            },
                        )()
                    ]
                },
            )()

    monkeypatch.setattr(
        "neo4j_graphrag.retrievers.VectorCypherRetriever", FakeVectorCypherRetriever
    )
    retriever = Neo4jVectorCypherRetriever(
        object(),
        index_name="chunk_embeddings",
        embedder=object(),
        database="neo4j",
        max_hops=2,
    )
    contexts = retriever.retrieve("show impact", project_slug="project-a", top_k=8)

    instance = FakeVectorCypherRetriever.instance
    assert instance is not None
    assert "relationships*1..2" in instance.kwargs["retrieval_query"]
    assert "all(item IN nodes(path) WHERE item:Entity)" in instance.kwargs["retrieval_query"]
    assert "node.project_slug = $project_slug" in instance.kwargs["retrieval_query"]
    assert instance.search_kwargs["query_params"] == {"project_slug": "project-a"}
    assert instance.search_kwargs["filters"] == {"project_slug": {"$eq": "project-a"}}
    assert contexts[0].entity_name == "Entity"


def test_evaluation_measures_supported_answers_and_refusal(tmp_path) -> None:
    source = tmp_path / "docs" / "customer.md"
    source.parent.mkdir()
    source.write_text("Billing depends on Customer Profile.", encoding="utf-8")

    def ask(question: str) -> QueryResponse:
        if "unknown" in question:
            return QueryResponse(
                answer="I do not have enough project evidence to answer that question.",
                warnings=["No context."],
                trace_id="refusal",
            )
        return QueryResponse(
            answer="Billing is affected [1].",
            citations=[
                Citation(
                    source_path="docs/customer.md",
                    evidence="Billing depends on Customer Profile.",
                )
            ],
            entities=[{"id": "billing", "name": "Billing", "type": "System"}],
            trace_id="supported",
        )

    report = evaluate_questions(
        [
            GoldenQuestion(
                id="impact",
                question="What is affected?",
                expected_entities=["Billing"],
                expected_sources=["docs/customer.md"],
            ),
            GoldenQuestion(id="no-answer", question="unknown", should_answer=False),
        ],
        ask,
        project_root=tmp_path,
    )

    assert report.passed == 2
    assert report.citation_validity == 1.0
    assert report.entity_retrieval == 1.0
    assert report.refusal_accuracy == 1.0


def test_evaluation_rejects_unresolved_inline_citations(tmp_path) -> None:
    source = tmp_path / "docs" / "customer.md"
    source.parent.mkdir()
    source.write_text("Evidence", encoding="utf-8")

    report = evaluate_questions(
        [GoldenQuestion(id="bad-citation", question="Impact?")],
        lambda question: QueryResponse(
            answer="Unsupported citation [2].",
            citations=[Citation(source_path="docs/customer.md", evidence="Evidence")],
            trace_id="trace",
        ),
        project_root=tmp_path,
    )

    assert report.passed == 0
    assert report.citation_validity == 0.0


def test_rag_api_uses_the_same_typed_contract(monkeypatch, tmp_path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    (tmp_path / ".env").write_text("SECRET=value", encoding="utf-8")
    portal = tmp_path / "portal"
    portal.mkdir()
    (portal / "index.html").write_text("Ontology Atlas", encoding="utf-8")
    diagnostics = tmp_path / "graphify-out"
    diagnostics.mkdir()
    (diagnostics / "GRAPH_REPORT.md").write_text("report", encoding="utf-8")
    (diagnostics / "graph.json").write_text("secret internals", encoding="utf-8")
    monkeypatch.setattr(
        "company_ontology_agent.api.app.get_rag_status",
        lambda root: RagStatus(
            ready=True,
            enabled=True,
            chunk_count=2,
            index_name="chunk_embeddings",
            message="GraphRAG is ready.",
        ),
    )
    monkeypatch.setattr(
        "company_ontology_agent.api.app.ask_project",
        lambda root, question: QueryResponse(answer=f"Answer: {question}", trace_id="trace"),
    )
    client = TestClient(create_app(tmp_path))

    assert client.get("/api/rag/status").json()["ready"] is True
    response = client.post("/api/rag/query", json={"question": "What changed?"})
    assert response.status_code == 200
    assert response.json()["answer"] == "Answer: What changed?"
    assert response.json()["trace_id"] == "trace"
    assert client.get("/.env").status_code == 404
    assert client.get("/graphify-out/GRAPH_REPORT.md").status_code == 200
    assert client.get("/graphify-out/graph.json").status_code == 404


def test_rag_api_rejects_blank_questions_and_maps_provider_errors(monkeypatch, tmp_path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    monkeypatch.setattr(
        "company_ontology_agent.api.app.ask_project",
        lambda root, question: (_ for _ in ()).throw(ValueError("provider unavailable")),
    )
    client = TestClient(create_app(tmp_path))

    assert client.post("/api/rag/query", json={"question": "   "}).status_code == 422
    response = client.post("/api/rag/query", json={"question": "What changed?"})
    assert response.status_code == 503
    assert response.json()["detail"] == "provider unavailable"


def test_rag_cli_exposes_required_commands() -> None:
    result = CliRunner().invoke(app, ["rag", "--help"])
    assert result.exit_code == 0
    for command in ["index", "ask", "status", "evaluate"]:
        assert command in result.stdout


@pytest.mark.neo4j
def test_live_neo4j_vector_index_retrieval_and_project_filtering() -> None:
    required = ["NEO4J_URI", "NEO4J_DATABASE", "NEO4J_USER", "NEO4J_PASSWORD"]
    if not all(os.getenv(name) for name in required):
        pytest.skip("Neo4j env vars are not configured.")
    if shutil.which("nc") and os.system("nc -z localhost 7687 >/dev/null 2>&1") != 0:
        pytest.skip("Neo4j is not reachable on localhost:7687.")

    project_slug = "ontology-atlas-live-test"
    decoy_slug = "ontology-atlas-live-decoy"
    index_name = "ontology_atlas_live_embeddings"
    graph = _graph().model_copy(deep=True)
    graph.project_slug = project_slug
    graph.sources[0].id = "live-rag-source"
    graph.source_spans[0].id = "live-rag-span"
    graph.source_spans[0].source_id = "live-rag-source"
    graph.entities[0].id = "live-rag-customer"
    graph.entities[0].source_span_ids = ["live-rag-span"]
    graph.entities[1].id = "live-rag-billing"
    graph.assertions[0].id = "live-rag-assertion"
    graph.assertions[0].subject_id = "live-rag-billing"
    graph.assertions[0].object_id = "live-rag-customer"
    graph.assertions[0].evidence_span_id = "live-rag-span"

    client = Neo4jClient(
        Neo4jConnection(
            uri=os.environ["NEO4J_URI"],
            username=os.environ["NEO4J_USER"],
            password=os.environ["NEO4J_PASSWORD"],
            database=os.environ["NEO4J_DATABASE"],
        )
    )
    try:
        client.execute(f"DROP INDEX {index_name} IF EXISTS")
        repository = Neo4jGraphRepository(client)
        repository.bootstrap()
        repository.upsert_graph(graph)
        result = KnowledgeIndexer(client, FakeEmbedder()).index(
            build_knowledge_chunks(graph),
            index_name=index_name,
            dimension=3,
            embedding_model="live-test-embedding",
        )
        client.execute(
            """
            CREATE (entity:Entity {id: 'live-rag-decoy-entity', name: 'Decoy',
                                   type: 'System', project_slug: $project_slug})
            CREATE (chunk:KnowledgeChunk {id: 'live-rag-decoy-chunk',
                                          project_slug: $project_slug,
                                          text: 'decoy', embedding: [0.1, 0.1, 0.1]})
            CREATE (chunk)-[:ABOUT]->(entity)
            """,
            {"project_slug": decoy_slug},
        )
        client.execute("CALL db.awaitIndex($index_name, 30)", {"index_name": index_name})

        contexts = Neo4jVectorCypherRetriever(
            client.driver,
            index_name=index_name,
            embedder=FakeEmbedder(),
            database=os.environ["NEO4J_DATABASE"],
            max_hops=2,
        ).retrieve("Customer Profile impact", project_slug=project_slug, top_k=8)

        assert result.total == 2
        assert contexts
        assert all(context.entity_id != "live-rag-decoy-entity" for context in contexts)
        assert {context.entity_id for context in contexts} <= {
            "live-rag-customer",
            "live-rag-billing",
        }
    finally:
        client.execute(
            "MATCH (node) WHERE node.project_slug IN $slugs DETACH DELETE node",
            {"slugs": [project_slug, decoy_slug]},
        )
        client.execute(f"DROP INDEX {index_name} IF EXISTS")
        client.close()
