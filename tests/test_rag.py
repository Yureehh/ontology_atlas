from __future__ import annotations

import os
import shutil
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import company_ontology_agent.retrieval.runtime as rag_runtime
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
from company_ontology_agent.retrieval.analytics import Neo4jAnalyticalEngine
from company_ontology_agent.retrieval.answer_composition import GraphRAGService, RetrievedContext
from company_ontology_agent.retrieval.answerer import Citation, QueryResponse
from company_ontology_agent.retrieval.evaluation import GoldenQuestion, evaluate_questions
from company_ontology_agent.retrieval.graphrag import (
    Neo4jOpenAIGenerator,
    Neo4jVectorCypherRetriever,
    _exact_lookup_alias_patterns,
    _exact_lookup_candidates,
    _preferred_direction,
    _preferred_predicates,
)
from company_ontology_agent.retrieval.indexing import KnowledgeIndexer, build_knowledge_chunks
from company_ontology_agent.retrieval.runtime import RagStatus, create_rag_runtime
from company_ontology_agent.retrieval.text2cypher import validate_generated_cypher


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
    assert config.rag.top_k == 4
    assert config.rag.max_hops == 2
    assert config.rag.analytics.enabled is True
    assert config.rag.analytics.text2cypher_local is True
    assert config.rag.analytics.max_hops == 3
    assert config.rag.analytics.max_rows == 100


def test_schema_driven_analytics_ranks_entities_without_scripted_answers() -> None:
    class Driver:
        queries: list[tuple[str, dict[str, object]]] = []

        def execute_query(self, query, parameters, **kwargs):
            query_text = getattr(query, "text", query)
            self.queries.append((query_text, parameters))
            if "RETURN entity.id AS id" in query_text:
                return (
                    [{"id": "league-lpl", "name": "LPL", "type": "League"}],
                    None,
                    None,
                )
            if "RETURN group_type" in query_text:
                return (
                    [
                        {
                            "group_type": "Match",
                            "predicates": [
                                "player_played_match",
                                "player_played_match",
                                "match_in_league",
                            ],
                            "intermediate_types": ["Player", "Match"],
                            "hops": 3,
                            "examples": 6240,
                        },
                        {
                            "group_type": "Player",
                            "predicates": ["player_played_match", "match_in_league"],
                            "intermediate_types": ["Match"],
                            "hops": 2,
                            "examples": 200,
                        },
                        {
                            "group_type": "Player",
                            "predicates": ["player_played_for", "team_in_league"],
                            "intermediate_types": ["Team"],
                            "hops": 2,
                            "examples": 20,
                        },
                    ],
                    None,
                    None,
                )
            assert parameters["project_slug"] == "portable"
            assert parameters["group_type"] == "Player"
            assert parameters["metric_type"] == "Match"
            return (
                [
                    {
                        "id": "player-a",
                        "name": "Player A",
                        "type": "Player",
                        "value": 18,
                        "source_paths": ["data/matches.parquet#matches:1"],
                        "paths": ["Player A → Match → LPL"],
                        "assertion_ids": ["played-1", "league-1"],
                    },
                    {
                        "id": "player-b",
                        "name": "Player B",
                        "type": "Player",
                        "value": 15,
                        "source_paths": ["data/matches.parquet#matches:2"],
                        "paths": ["Player B → Match → LPL"],
                        "assertion_ids": ["played-2", "league-2"],
                    },
                ],
                None,
                None,
            )

    engine = Neo4jAnalyticalEngine(Driver(), database="neo4j", max_hops=3, max_rows=100)
    response = engine.try_answer(
        "Who played the most games in LPL?", project_slug="portable"
    )

    assert response is not None
    assert "Player A" in response.answer and "18" in response.answer
    assert response.analysis is not None
    assert response.analysis.mode == "safe_analytics"
    assert response.analysis.metric == "distinct Match"
    assert response.analysis.rows[0]["value"] == 18
    assert response.citations[0].source_path == "data/matches.parquet"
    assert response.paths[0]["summary"] == "Player A → Match → LPL"


def test_analytics_ignores_non_analytical_and_unsupported_questions() -> None:
    class Driver:
        def execute_query(self, query, parameters, **kwargs):
            return ([], None, None)

    engine = Neo4jAnalyticalEngine(Driver(), database="neo4j")

    assert engine.try_answer("How does billing work?", project_slug="portable") is None
    assert (
        engine.try_answer("Who played the most games in Atlantis?", project_slug="portable")
        is None
    )


def test_schema_driven_analytics_is_portable_to_services_and_incidents() -> None:
    class Driver:
        def execute_query(self, query, parameters, **kwargs):
            query_text = getattr(query, "text", query)
            if "RETURN entity.id AS id" in query_text:
                return ([{"id": "region-eu", "name": "EU", "type": "Region"}], None, None)
            if "RETURN group_type" in query_text:
                return (
                    [{
                        "group_type": "Service",
                        "predicates": ["service_has_incident", "incident_in_region"],
                        "intermediate_types": ["Incident"],
                        "hops": 2,
                        "examples": 14,
                    }],
                    None,
                    None,
                )
            assert parameters["group_type"] == "Service"
            assert parameters["metric_type"] == "Incident"
            return (
                [{
                    "id": "checkout",
                    "name": "Checkout",
                    "type": "Service",
                    "value": 7,
                    "source_paths": ["data/incidents.csv#row=4"],
                    "paths": ["Checkout → Incident → EU"],
                    "assertion_ids": ["incident-4"],
                }],
                None,
                None,
            )

    response = Neo4jAnalyticalEngine(Driver(), database="neo4j").try_answer(
        "Which service had the most incidents in EU?", project_slug="operations"
    )

    assert response is not None
    assert "Checkout" in response.answer and "7" in response.answer
    assert response.analysis is not None
    assert response.analysis.grouping == ["Service"]
    assert response.analysis.metric == "distinct Incident"
    assert response.citations[0].source_path == "data/incidents.csv"


def test_schema_driven_analytics_counts_direct_relationships() -> None:
    class Driver:
        def execute_query(self, query, parameters, **kwargs):
            query_text = getattr(query, "text", query)
            if "RETURN entity.id AS id" in query_text:
                return ([{"id": "region-eu", "name": "EU", "type": "Region"}], None, None)
            if "RETURN group_type" in query_text:
                return (
                    [{
                        "group_type": "Service",
                        "predicates": ["service_in_region"],
                        "intermediate_types": [],
                        "hops": 1,
                        "examples": 3,
                    }],
                    None,
                    None,
                )
            assert parameters["group_type"] == "Service"
            return (
                [{
                    "name": "Service",
                    "value": 3,
                    "source_paths": ["data/services.csv#row=1"],
                    "paths": ["Checkout → EU"],
                    "assertion_groups": [["service-region-1"]],
                }],
                None,
                None,
            )

    response = Neo4jAnalyticalEngine(Driver(), database="neo4j").try_answer(
        "How many services are in EU?", project_slug="operations"
    )

    assert response is not None
    assert response.answer == "There are **3 distinct Service** connected to **EU**."
    assert response.analysis is not None
    assert response.analysis.operation == "count"
    assert response.citations[0].source_path == "data/services.csv"


def test_deterministic_analytics_defers_numeric_aggregates_to_expert_planner() -> None:
    class Driver:
        def execute_query(self, query, parameters, **kwargs):
            raise AssertionError("numeric aggregates must fall through before database access")

    engine = Neo4jAnalyticalEngine(Driver(), database="neo4j")

    assert engine.try_answer("What is the average order value?", project_slug="shop") is None


def test_text2cypher_validation_enforces_project_scope_and_bounds() -> None:
    valid = validate_generated_cypher(
        """MATCH (project:Project {slug: $project_slug})-[:HAS_ENTITY]->(entity:Entity)
        MATCH path=(entity)-[relationships*1..3]-(neighbor:Entity)
        WHERE EXISTS { MATCH (project)-[:HAS_ENTITY]->(neighbor) }
        RETURN entity.name AS name, count(neighbor) AS value,
               collect(entity.source_path) AS source_paths, collect(entity.name) AS paths""",
        max_hops=3,
        max_rows=100,
    )
    assert valid.endswith("LIMIT 100")

    for unsafe in [
        "MATCH (n) DELETE n RETURN n",
        "CALL db.labels() YIELD label RETURN label",
        "MATCH (n)-[*]-(m) RETURN n LIMIT 10",
        "MATCH (project:Project)-[:HAS_ENTITY]->(n) RETURN n LIMIT 10",
        "MATCH (project:Project {slug: $project_slug})-[:HAS_ENTITY]->(n) RETURN n; DELETE n",
        "MATCH (project:Project {slug: $project_slug})-[:HAS_ENTITY]->(safe:Entity) "
        "MATCH (unscoped:Entity) RETURN unscoped.name AS name LIMIT 10",
        "MATCH (project:Project {slug: $project_slug})-[:HAS_ENTITY]->(safe:Entity) "
        "MATCH (safe)-[]-()-[]-()-[]-()-[]-(other:Entity) "
        "WHERE EXISTS { MATCH (project)-[:HAS_ENTITY]->(other) } RETURN safe LIMIT 10",
        "MATCH (project:Project {slug: $project_slug})-[:HAS_ENTITY]->(safe:Entity) "
        "MATCH (foreign:Customer) RETURN foreign LIMIT 10",
        "MATCH (project:Project {slug: $project_slug})-[:HAS_ENTITY]->(safe:Entity) "
        "MATCH (safe)-[]-(foreign) RETURN foreign LIMIT 10",
        "MATCH (project:Project {slug: $project_slug})-[:HAS_ENTITY]->(safe:Entity) "
        "MATCH (other:Project)-[:HAS_ENTITY]->(foreign:Entity) RETURN foreign LIMIT 10",
    ]:
        with pytest.raises(ValueError):
            validate_generated_cypher(unsafe, max_hops=3, max_rows=100)


def test_text2cypher_limits_oversized_results() -> None:
    bounded = validate_generated_cypher(
        "MATCH (project:Project {slug: $project_slug})-[:HAS_ENTITY]->(entity:Entity) "
        "RETURN entity.name AS name LIMIT 9999",
        max_hops=3,
        max_rows=25,
    )
    assert bounded.endswith("LIMIT 25")


def test_text2cypher_allows_only_cataloged_numeric_aggregations() -> None:
    query = (
        "MATCH (project:Project {slug: $project_slug})-[:HAS_ENTITY]->(entity:Entity) "
        "RETURN 'Average' AS name, avg(entity.attr_score) AS value, "
        "collect(entity.source_path) AS source_paths, collect(entity.name) AS paths LIMIT 10"
    )
    assert validate_generated_cypher(
        query,
        max_hops=3,
        max_rows=100,
        allowed_properties={"attr_score", "attr_date"},
        numeric_properties={"attr_score"},
    ).endswith("LIMIT 10")

    for unsafe in [
        query.replace("attr_score", "attr_secret"),
        query.replace("attr_score", "attr_date"),
        query.replace("avg(entity.attr_score)", "rand()"),
    ]:
        with pytest.raises(ValueError):
            validate_generated_cypher(
                unsafe,
                max_hops=3,
                max_rows=100,
                allowed_properties={"attr_score", "attr_date"},
                numeric_properties={"attr_score"},
            )


def test_exact_lookup_candidates_keep_names_and_drop_generic_question_terms() -> None:
    assert _exact_lookup_candidates("What team does Bin play for?") == ["bin"]
    assert _exact_lookup_candidates("Which team does bin play for?") == ["bin"]
    assert _exact_lookup_candidates("What team is Bin on?") == ["bin"]
    assert _exact_lookup_candidates("Bin's team?") == ["bin"]
    assert _exact_lookup_candidates("Who plays for BLG?") == ["blg"]
    assert _exact_lookup_candidates("Which players play for BLG?") == ["blg"]
    assert "4 swines & a bum" in _exact_lookup_candidates(
        "Which players play for 4 Swines & A Bum?"
    )
    assert "anyone's legend" in _exact_lookup_candidates(
        "Which league does Anyone's Legend compete in?"
    )
    assert _exact_lookup_alias_patterns("Who plays for BLG?") == ["(?i).*B.*L.*G.*"]
    assert _exact_lookup_alias_patterns("What team is Bin on?") == []
    assert _exact_lookup_candidates(
        "What is the authoritative source for mapping teams to leagues?"
    ) == []
    assert _preferred_predicates("Which league does Axolotl compete in?") == [
        "league",
        "axolotl",
        "compete",
    ]
    assert _preferred_direction("What does GradientBoostingModel use?") == "outgoing"
    assert _preferred_direction("What uses GradientBoostingModel?") == "incoming"
    assert _preferred_direction("Who plays for BLG?") == "incoming"
    assert _preferred_direction("Which players play for BLG?") == "incoming"


def test_build_knowledge_chunks_is_deterministic_and_traceable() -> None:
    first = build_knowledge_chunks(_graph())
    second = build_knowledge_chunks(_graph())

    assert first == second
    customer = next(chunk for chunk in first if chunk.entity_id == "customer")
    assert customer.kind == "entity"
    assert customer.title == "Customer Profile"
    assert customer.evidence_level == "mixed"
    assert customer.source_paths == ["docs/customer.md"]
    assert customer.source_span_ids == ["span-1"]
    assert "Billing depends_on Customer Profile" in customer.text


def test_build_knowledge_chunks_aggregates_structured_rows_by_dataset_and_type() -> None:
    rows = [
        Entity(
            id=f"team-{index}",
            type=EntityType.business_entity,
            name=f"Team {index}",
            normalized_name=f"team {index}",
            extraction_source="structured_connector",
            source_path=f"models/lol/team_league_mapping.parquet#teams:{index}",
            metadata={
                "dataset": "team_league_mapping",
                "domain": "league_of_legends",
                "connector": "parquet",
                "mapped_type": "Team",
                "record_key": str(index),
            },
        )
        for index in range(100)
    ]
    graph = ExtractedGraph(
        project_slug="oracle",
        entities=[
            *rows,
            Entity(
                id="team-summary",
                type=EntityType.concept,
                name="Team in team_league_mapping",
                normalized_name="team in team league mapping",
                extraction_source="structured_connector",
                metadata={
                    "dataset": "team_league_mapping",
                    "mapped_type": "Team",
                    "semantic_summary": True,
                    "record_count": 100,
                },
            ),
        ],
    )

    chunks = build_knowledge_chunks(graph)

    assert {chunk.kind for chunk in chunks} == {"dataset", "domain"}
    assert len(chunks) == 2
    assert all("100" in chunk.text for chunk in chunks)
    assert all("team_league_mapping.parquet" in chunk.text for chunk in chunks)
    assert not any(chunk.title == "Team 42" for chunk in chunks)


def test_structured_summaries_hide_opaque_record_identifiers() -> None:
    graph = ExtractedGraph(
        project_slug="oracle",
        entities=[
            Entity(
                id="team-1",
                type=EntityType.business_entity,
                name="oe:team:7338408a0fe0217451d2c9a567db999",
                normalized_name="oe:team:7338408a0fe0217451d2c9a567db999",
                extraction_source="structured_connector",
                source_path="models/lol/team_league_mapping.parquet#team_league_mapping:1",
                metadata={
                    "dataset": "team_league_mapping",
                    "domain": "league_of_legends",
                    "connector": "parquet",
                    "mapped_type": "Team",
                    "record_key": "oe:team:7338408a0fe0217451d2c9a567db999",
                },
            )
        ],
    )

    chunks = build_knowledge_chunks(graph)

    assert chunks
    assert all("oe:team:" not in chunk.text for chunk in chunks)


def test_knowledge_chunk_hash_covers_traceability_metadata() -> None:
    original = build_knowledge_chunks(_graph())
    changed_graph = _graph().model_copy(deep=True)
    changed_graph.entities[0].source_path = "docs/renamed-customer.md"

    changed = build_knowledge_chunks(changed_graph)

    original_customer = next(
        chunk for chunk in original if chunk.entity_id == "customer" and chunk.kind == "entity"
    )
    changed_customer = next(
        chunk for chunk in changed if chunk.entity_id == "customer" and chunk.kind == "entity"
    )
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


class FakeBatchEmbedder(FakeEmbedder):
    def __init__(self, dimension: int = 3) -> None:
        super().__init__(dimension)
        self.batches: list[list[str]] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(texts)
        return [[0.1] * self.dimension for _ in texts]


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


def test_indexer_batches_neo4j_writes() -> None:
    template = build_knowledge_chunks(_graph())[0]
    chunks = [
        template.model_copy(
            update={
                "id": f"chunk-{index}",
                "entity_id": f"entity-{index}",
                "source_span_ids": [],
            }
        )
        for index in range(205)
    ]
    client = FakeClient()

    result = KnowledgeIndexer(client, FakeEmbedder()).index(
        chunks,
        index_name="chunk_embeddings",
        dimension=3,
        embedding_model="test-embedding",
    )

    batched_writes = [
        parameters["chunks"]
        for statement, parameters in client.calls
        if "UNWIND $chunks AS row" in statement
    ]
    assert result.indexed == 205
    assert [len(batch) for batch in batched_writes] == [100, 100, 5]


def test_indexer_batches_embedding_requests_when_supported() -> None:
    template = build_knowledge_chunks(_graph())[0]
    chunks = [
        template.model_copy(update={"id": f"chunk-{index}", "entity_id": f"entity-{index}"})
        for index in range(65)
    ]
    embedder = FakeBatchEmbedder()

    result = KnowledgeIndexer(FakeClient(), embedder).index(
        chunks,
        index_name="chunk_embeddings",
        dimension=3,
        embedding_model="test-embedding",
    )

    assert result.indexed == 65
    assert [len(batch) for batch in embedder.batches] == [32, 32, 1]
    assert embedder.texts == []


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


class FakeTimedRetriever(FakeRetriever):
    def retrieve_with_timings(
        self, question: str, *, project_slug: str, top_k: int
    ) -> tuple[list[RetrievedContext], dict[str, float]]:
        return self.retrieve(question, project_slug=project_slug, top_k=top_k), {
            "embedding": 10.0,
            "vector_search": 20.0,
            "traversal": 30.0,
        }


def test_openai_generator_uses_fast_bounded_reasoning(monkeypatch: pytest.MonkeyPatch) -> None:
    import neo4j_graphrag.llm

    calls: list[dict[str, object]] = []

    class FakeLLM:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

        def invoke(self, prompt: str) -> str:
            return prompt

    monkeypatch.setattr(neo4j_graphrag.llm, "OpenAILLM", FakeLLM)

    Neo4jOpenAIGenerator(model_name="gpt-5.5", api_key="test-key")

    assert calls == [
        {
            "model_name": "gpt-5.5",
            "api_key": "test-key",
            "timeout": 45.0,
            "max_retries": 1,
            "model_params": {
                "max_completion_tokens": 1000,
                "reasoning_effort": "none",
            },
        }
    ]


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
    assert "one to three sentences" in generator.prompts[0]


def test_graphrag_service_humanizes_internal_predicates_in_answers() -> None:
    context = RetrievedContext(
        chunk_id="chunk-1",
        text="Team record belongs to LEC.",
        entity_id="team",
        entity_name="Team record",
        entity_type="Team",
        source_paths=["data/teams.parquet"],
    )
    response = GraphRAGService(
        FakeRetriever([context]),
        FakeGenerator("`Team record -[TEAM_IN_LEAGUE]-> LEC`.[1]"),
    ).ask("Which league?", project_slug="demo", top_k=4)

    assert response.answer == "`Team record team in league LEC`.[1]"
    assert "TEAM_IN_LEAGUE" not in response.answer


def test_graphrag_service_reports_real_retrieval_phase_timings() -> None:
    context = RetrievedContext(
        chunk_id="chunk-1",
        text="Billing depends on Customer Profile.",
        entity_id="billing",
        entity_name="Billing",
        entity_type="System",
        source_paths=["docs/customer.md"],
    )

    response = GraphRAGService(
        FakeTimedRetriever([context]), FakeGenerator()
    ).ask("What is affected?", project_slug="customer-platform", top_k=4)

    assert response.timings_ms["embedding"] == 10.0
    assert response.timings_ms["vector_search"] == 20.0
    assert response.timings_ms["traversal"] == 30.0
    assert response.timings_ms["total"] >= response.timings_ms["generation"]


def test_query_response_renders_safe_markdown() -> None:
    response = QueryResponse(
        answer="## Result\n\n- Use `league_elo.parquet`\n\n<script>alert(1)</script>",
        trace_id="trace",
    )

    assert "<h2>Result</h2>" in response.answer_html
    assert "<li>Use <code>league_elo.parquet</code></li>" in response.answer_html
    assert "<script>" not in response.answer_html
    assert "&lt;script&gt;" in response.answer_html


def test_graphrag_service_caps_the_explanation_neighborhood() -> None:
    context = RetrievedContext(
        chunk_id="chunk-1",
        text="Evidence.",
        entity_id="entity-1",
        entity_name="Entity",
        entity_type="System",
        source_paths=["docs/evidence.md"],
        paths=[f"path-{index}" for index in range(75)],
        assertion_ids=[f"assertion-{index}" for index in range(75)],
    )

    response = GraphRAGService(FakeRetriever([context]), FakeGenerator()).ask(
        "What changes?", project_slug="customer-platform", top_k=5
    )

    assert len(response.paths) == 12
    assert len(response.supporting_assertions) == 12


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

    class RetrieverEmbedder:
        def embed_query(self, text: str) -> list[float]:
            assert text == "show impact"
            return [0.1, 0.2]

    class RetrieverDriver:
        def execute_query(self, query, parameters, **kwargs):
            if "candidate_names" in parameters:
                assert "candidate_patterns" in parameters
                return ([], None, None)
            assert parameters == {
                "project_slug": "project-a",
                "entity_ids": ["entity"],
            }
            return (
                [
                    {
                        "entity_id": "entity",
                        "paths": ["Entity -[USES]-> Evidence"],
                        "assertion_ids": ["assertion-1"],
                    }
                ],
                None,
                None,
            )

    retriever = Neo4jVectorCypherRetriever(
        RetrieverDriver(),
        index_name="chunk_embeddings",
        embedder=RetrieverEmbedder(),
        database="neo4j",
        max_hops=2,
    )
    contexts, timings = retriever.retrieve_with_timings(
        "show impact", project_slug="project-a", top_k=8
    )

    instance = FakeVectorCypherRetriever.instance
    assert instance is not None
    assert "relationships*1..2" in retriever._traversal_query
    assert "all(item IN nodes(path) WHERE item:Entity" in retriever._traversal_query
    assert "EXISTS { MATCH (project)-[:HAS_ENTITY]->(item) }" in retriever._traversal_query
    assert "coalesce(item.stale, false) = false" in retriever._traversal_query
    assert "CALL (entity, project)" in retriever._traversal_query
    assert "ORDER BY relevance, length(path), neighbor.name" in retriever._traversal_query
    assert "node.project_slug = $project_slug" in instance.kwargs["retrieval_query"]
    assert "coalesce(rel.assertion_id, rel.id)" in retriever._traversal_query
    assert instance._node_embedding_property == "embedding"
    assert instance.search_kwargs["query_vector"] == [0.1, 0.2]
    assert instance.search_kwargs["query_params"] == {"project_slug": "project-a"}
    assert instance.search_kwargs["filters"] == {"project_slug": {"$eq": "project-a"}}
    assert contexts[0].entity_name == "Entity"
    assert contexts[0].paths == ["Entity -[USES]-> Evidence"]
    assert set(timings) == {"exact_lookup", "embedding", "vector_search", "traversal"}


def test_official_retriever_resolves_named_business_entity_before_vector_search(
    monkeypatch,
) -> None:
    pytest.importorskip("neo4j_graphrag")

    class FakeVectorCypherRetriever:
        def __init__(self, driver, **kwargs):
            self._node_embedding_property = "embedding"

        def search(self, **kwargs):
            pytest.fail("exact entity lookup should avoid irrelevant vector retrieval")

    monkeypatch.setattr(
        "neo4j_graphrag.retrievers.VectorCypherRetriever", FakeVectorCypherRetriever
    )

    class RetrieverEmbedder:
        def embed_query(self, text: str) -> list[float]:
            pytest.fail("exact entity lookup should not create a query embedding")

    class RetrieverDriver:
        def execute_query(self, query, parameters, **kwargs):
            assert parameters["project_slug"] == "project-a"
            assert "bin" in parameters["candidate_names"]
            assert "team" not in parameters["candidate_names"]
            assert parameters["preferred_predicates"] == ["team", "bin", "play"]
            assert parameters["preferred_direction"] == "outgoing"
            assert "coalesce(entity.stale, false) = false" in query
            assert "EXISTS { MATCH (project)-[:HAS_ENTITY]->(neighbor) }" in query
            return (
                [
                    {
                        "entity_id": "player-bin",
                        "entity_name": "Bin",
                        "entity_type": "Player",
                        "source_path": "data/lol/raw_data.parquet#raw_data:937",
                        "source_span_ids": ["span-bin"],
                        "metadata_json": (
                            '{"teamname":"Bilibili Gaming","league":"LPL",'
                            '"_origin":"ast","community_id":14}'
                        ),
                        "extraction_source": "structured_connector",
                        "facts": [
                            {
                                "predicate": "player_played_for",
                                "neighbor_name": "Bilibili Gaming",
                                "direction": "outgoing",
                                "source_path": "data/lol/raw_data.parquet#raw_data:937",
                                "assertion_id": "assertion-bin-team",
                            }
                        ],
                    }
                ],
                None,
                None,
            )

    retriever = Neo4jVectorCypherRetriever(
        RetrieverDriver(),
        index_name="chunk_embeddings",
        embedder=RetrieverEmbedder(),
        database="neo4j",
        max_hops=2,
    )

    contexts, timings = retriever.retrieve_with_timings(
        "What team does Bin play for?", project_slug="project-a", top_k=4
    )

    assert len(contexts) == 1
    assert contexts[0].entity_name == "Bin"
    assert "Bilibili Gaming" in contexts[0].text
    assert "_origin" not in contexts[0].text
    assert "community_id" not in contexts[0].text
    assert contexts[0].paths == ["Bin -[player_played_for]-> Bilibili Gaming"]
    assert contexts[0].assertion_ids == ["assertion-bin-team"]
    assert contexts[0].source_paths == ["data/lol/raw_data.parquet#raw_data:937"]
    assert timings["embedding"] == 0.0
    assert timings["vector_search"] == 0.0


def test_exact_lookup_falls_back_when_the_named_entity_has_no_relevant_facts(
    monkeypatch,
) -> None:
    pytest.importorskip("neo4j_graphrag")

    class FakeVectorCypherRetriever:
        def __init__(self, driver, **kwargs):
            self._node_embedding_property = "embedding"

        def search(self, **kwargs):
            return type(
                "Result",
                (),
                {
                    "items": [
                        type(
                            "Item",
                            (),
                            {
                                "content": {
                                    "chunk_id": "semantic-1",
                                    "text": "BLG is supported by semantic evidence.",
                                    "entity_id": "team-blg",
                                    "entity_name": "Bilibili Gaming",
                                    "entity_type": "Team",
                                }
                            },
                        )()
                    ]
                },
            )()

    monkeypatch.setattr(
        "neo4j_graphrag.retrievers.VectorCypherRetriever", FakeVectorCypherRetriever
    )

    class Embedder:
        def embed_query(self, text: str) -> list[float]:
            return [0.1, 0.2]

    class Driver:
        calls = 0

        def execute_query(self, query, parameters, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return (
                    [
                        {
                            "entity_id": "team-blg",
                            "entity_name": "Bilibili Gaming",
                            "entity_type": "Team",
                            "facts": [],
                        }
                    ],
                    None,
                    None,
                )
            return ([], None, None)

    retriever = Neo4jVectorCypherRetriever(
        Driver(),
        index_name="chunk_embeddings",
        embedder=Embedder(),
        database="neo4j",
        max_hops=2,
    )

    contexts, timings = retriever.retrieve_with_timings(
        "Who plays for BLG?", project_slug="project-a", top_k=4
    )

    assert contexts[0].chunk_id == "semantic-1"
    assert timings["embedding"] >= 0


def test_exact_citations_separate_artifact_path_from_record_locator() -> None:
    service = GraphRAGService(
        FakeRetriever(
            [
                RetrievedContext(
                    chunk_id="exact:bin",
                    text="Bin plays for Bilibili Gaming.",
                    entity_id="bin",
                    entity_name="Bin",
                    entity_type="Player",
                    source_paths=["data/lol/raw_data.parquet#raw_data:937"],
                    evidence_level="authoritative",
                )
            ]
        ),
        FakeGenerator("Bin plays for Bilibili Gaming [1]."),
    )

    response = service.ask("Bin's team?", project_slug="project-a", top_k=4)

    assert response.citations[0].source_path == "data/lol/raw_data.parquet"
    assert response.citations[0].record_locator == "raw_data:937"


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
            paths=[{"summary": "Billing -[depends_on]-> Customer Profile"}],
            trace_id="supported",
        )

    report = evaluate_questions(
        [
            GoldenQuestion(
                id="impact",
                question="What is affected?",
                expected_entities=["Billing"],
                expected_sources=["docs/customer.md"],
                expected_relationships=["depends_on"],
            ),
            GoldenQuestion(id="no-answer", question="unknown", should_answer=False),
        ],
        ask,
        project_root=tmp_path,
    )

    assert report.passed == 2
    assert report.citation_validity == 1.0
    assert report.entity_retrieval == 1.0
    assert report.relationship_retrieval == 1.0
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


def test_evaluation_resolves_nested_project_sources_and_checks_only_used_citations(
    tmp_path,
) -> None:
    project_root = tmp_path / ".ontology-agent"
    project_root.mkdir()
    source = tmp_path / "packages" / "prediction.py"
    source.parent.mkdir()
    source.write_text("predict", encoding="utf-8")

    report = evaluate_questions(
        [GoldenQuestion(id="nested-source", question="Impact?")],
        lambda question: QueryResponse(
            answer="Prediction is implemented here [1].",
            citations=[
                Citation(source_path="packages/prediction.py", evidence="predict"),
                Citation(source_path="missing/unused.md", evidence="unused context"),
            ],
            trace_id="trace",
        ),
        project_root=project_root,
    )

    assert report.passed == 1
    assert report.citation_validity == 1.0


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
    (diagnostics / "graph.html").write_text("raw graphify map", encoding="utf-8")
    (diagnostics / "graph.json").write_text("secret internals", encoding="utf-8")

    class FakeRuntime:
        def status(self) -> RagStatus:
            return RagStatus(
                ready=True,
                enabled=True,
                chunk_count=2,
                index_name="chunk_embeddings",
                message="GraphRAG is ready.",
            )

        def ask(self, question: str) -> QueryResponse:
            return QueryResponse(answer=f"Answer: {question}", trace_id="trace")

        def search_entities(self, query: str, *, layer: str, limit: int):
            return [{"i": "bin", "n": "Bin", "t": "Player", "layer": "data"}]

        def close(self) -> None:
            return None

    client = TestClient(create_app(tmp_path, runtime=FakeRuntime()))

    assert client.get("/api/rag/status").json()["ready"] is True
    response = client.post("/api/rag/query", json={"question": "What changed?"})
    assert response.status_code == 200
    assert response.json()["answer"] == "Answer: What changed?"
    assert response.json()["trace_id"] == "trace"
    assert client.get("/.env").status_code == 404
    assert client.get("/graphify-out/GRAPH_REPORT.md").status_code == 200
    assert client.get("/graphify-out/graph.html").status_code == 200
    assert client.get("/graphify-out/graph.json").status_code == 404
    search = client.get("/api/entities/search?q=bin&layer=data&limit=10")
    assert search.status_code == 200
    assert search.json()["results"][0]["n"] == "Bin"


def test_rag_api_rejects_blank_questions_and_maps_provider_errors(monkeypatch, tmp_path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    class FailingRuntime:
        def ask(self, question: str) -> QueryResponse:
            raise ValueError("provider unavailable")

        def close(self) -> None:
            return None

    client = TestClient(create_app(tmp_path, runtime=FailingRuntime()))

    assert client.post("/api/rag/query", json={"question": "   "}).status_code == 422
    response = client.post("/api/rag/query", json={"question": "What changed?"})
    assert response.status_code == 503
    assert response.json()["detail"]["message"] == "GraphRAG is unavailable."
    assert "provider unavailable" not in response.text

    class TimeoutRuntime(FailingRuntime):
        def ask(self, question: str) -> QueryResponse:
            raise TimeoutError("provider timed out")

    timeout_client = TestClient(create_app(tmp_path, runtime=TimeoutRuntime()))
    timeout_response = timeout_client.post(
        "/api/rag/query", json={"question": "What changed?"}
    )
    assert timeout_response.status_code == 504
    assert timeout_response.json()["detail"]["message"] == "GraphRAG query timed out."


def test_rag_api_reuses_one_runtime_across_questions(monkeypatch, tmp_path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    created: list[object] = []

    class FakeRuntime:
        def ask(self, question: str) -> QueryResponse:
            return QueryResponse(answer=question, trace_id="trace")

        def close(self) -> None:
            return None

    def factory(root):
        runtime = FakeRuntime()
        created.append(runtime)
        return runtime

    monkeypatch.setattr("company_ontology_agent.api.app.create_rag_runtime", factory)
    client = TestClient(create_app(tmp_path))

    assert client.post("/api/rag/query", json={"question": "First"}).status_code == 200
    assert client.post("/api/rag/query", json={"question": "Second"}).status_code == 200
    assert len(created) == 1


def test_rag_api_enables_expert_planner_only_when_explicitly_allowed(
    monkeypatch, tmp_path
) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    calls: list[bool] = []

    class FakeRuntime:
        def ask(self, question: str) -> QueryResponse:
            return QueryResponse(answer=question, trace_id="trace")

        def close(self) -> None:
            return None

    def factory(root, *, allow_text2cypher=False):
        calls.append(allow_text2cypher)
        return FakeRuntime()

    monkeypatch.setattr("company_ontology_agent.api.app.create_rag_runtime", factory)
    default_client = TestClient(create_app(tmp_path))
    local_client = TestClient(create_app(tmp_path, allow_text2cypher=True))

    assert default_client.post("/api/rag/query", json={"question": "First"}).status_code == 200
    assert local_client.post("/api/rag/query", json={"question": "Second"}).status_code == 200
    assert calls == [False, True]


def test_runtime_closes_neo4j_when_partial_construction_fails(monkeypatch, tmp_path) -> None:
    config = default_config("demo")
    config.rag.enabled = True
    client = SimpleNamespace(close_calls=0, driver=object())
    client.close = lambda: setattr(client, "close_calls", client.close_calls + 1)

    monkeypatch.setattr(rag_runtime, "load_project_config", lambda root: config)
    monkeypatch.setattr(
        rag_runtime,
        "runtime_settings",
        lambda cfg: SimpleNamespace(neo4j_database="neo4j"),
    )
    monkeypatch.setattr(rag_runtime, "_validate", lambda *args, **kwargs: None)
    monkeypatch.setattr(rag_runtime, "_client", lambda *args: client)
    monkeypatch.setattr(
        rag_runtime,
        "_embedder",
        lambda *args: (_ for _ in ()).throw(RuntimeError("embedder failed")),
    )

    with pytest.raises(RuntimeError, match="embedder failed"):
        create_rag_runtime(tmp_path)

    assert client.close_calls == 1


def test_entity_search_is_project_filtered_and_bounded() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class Client:
        def query(self, query: str, parameters: dict[str, object]):
            calls.append((query, parameters))
            return [{"id": "bin", "name": "Bin", "type": "Player", "layer": "data"}]

        def close(self) -> None:
            return None

    config = default_config("oracle")
    runtime = rag_runtime.ProjectRagRuntime(
        config=config,
        client=Client(),  # type: ignore[arg-type]
        service=SimpleNamespace(),  # type: ignore[arg-type]
    )

    results = runtime.search_entities("BIN", layer="data", limit=999)

    assert results == [{"i": "bin", "n": "Bin", "t": "Player", "layer": "data"}]
    assert calls[0][1] == {
        "project_slug": "oracle",
        "query": "bin",
        "layer": "data",
        "limit": 50,
    }
    assert "HAS_ENTITY" in calls[0][0]


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
    owns_index = False
    try:
        existing_indexes = client.query(
            """
            SHOW VECTOR INDEXES YIELD name, labelsOrTypes, properties, options
                WHERE labelsOrTypes = ['KnowledgeChunk'] AND properties[0] = 'embedding'
            RETURN name, options
            LIMIT 1
            """
        )
        dimension = 3
        if existing_indexes:
            index_name = str(existing_indexes[0]["name"])
            options = existing_indexes[0].get("options") or {}
            dimension = int(options.get("indexConfig", {}).get("vector.dimensions", 3))
        else:
            client.execute(f"DROP INDEX {index_name} IF EXISTS")
            owns_index = True
        repository = Neo4jGraphRepository(client)
        repository.bootstrap()
        repository.upsert_graph(graph)
        embedder = FakeEmbedder(dimension)
        result = KnowledgeIndexer(client, embedder).index(
            build_knowledge_chunks(graph),
            index_name=index_name,
            dimension=dimension,
            embedding_model="live-test-embedding",
        )
        client.execute(
            """
            CREATE (entity:Entity {id: 'live-rag-decoy-entity', name: 'Decoy',
                                   type: 'System', project_slug: $project_slug})
                CREATE (chunk:KnowledgeChunk {id: 'live-rag-decoy-chunk',
                                              project_slug: $project_slug,
                                              text: 'decoy',
                                              embedding: [x IN range(1, $dimension) | 0.1]})
            CREATE (chunk)-[:ABOUT]->(entity)
            """,
            {"project_slug": decoy_slug, "dimension": dimension},
        )
        client.execute("CALL db.awaitIndex($index_name, 30)", {"index_name": index_name})

        contexts = Neo4jVectorCypherRetriever(
            client.driver,
            index_name=index_name,
            embedder=embedder,
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
        if owns_index:
            client.execute(f"DROP INDEX {index_name} IF EXISTS")
        client.close()


def test_document_ingestion_builds_sources_chunks_and_knowledge_chunks(tmp_path) -> None:
    from company_ontology_agent.ingestion.documents import build_document_graph

    config = default_config("demo")
    config.rag.document_chunk_chars = 300
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    body = "\n\n".join(f"Paragraph {index} " + "x" * 150 for index in range(6))
    (raw / "guide.md").write_text(f"# Guide\n\n{body}", encoding="utf-8")
    (raw / "empty.txt").write_text("   ", encoding="utf-8")

    graph = build_document_graph(tmp_path, config)

    assert [source.source_type for source in graph.sources] == ["document"]
    assert graph.sources[0].path == "guide.md"
    assert graph.entities[0].source_path == "guide.md"
    assert len(graph.chunks) >= 2
    assert "Paragraph 5" in "\n".join(chunk.text for chunk in graph.chunks)

    chunks = build_knowledge_chunks(graph)
    document_chunks = [chunk for chunk in chunks if chunk.kind == "document"]
    assert document_chunks
    assert all(chunk.source_paths == ["guide.md"] for chunk in document_chunks)
    assert all(chunk.text.startswith("Document: guide.md") for chunk in document_chunks)

    capped = build_knowledge_chunks(graph, document_chunk_limit=1)
    assert len([chunk for chunk in capped if chunk.kind == "document"]) == 1


def test_entity_chunk_limit_is_configurable() -> None:
    chunks = build_knowledge_chunks(_graph(), entity_limit=1)
    assert len([chunk for chunk in chunks if chunk.kind == "entity"]) == 1


def test_weak_only_evidence_adds_warning() -> None:
    retriever = FakeRetriever(
        [
            RetrievedContext(
                chunk_id="chunk-1",
                text="Loosely related text.",
                entity_id="entity-1",
                entity_name="Thing",
                entity_type="Concept",
                evidence_level="weak",
            )
        ]
    )

    response = GraphRAGService(retriever, FakeGenerator()).ask(
        "What is affected?", project_slug="demo", top_k=4
    )

    assert any("weak" in warning for warning in response.warnings)


def test_status_flags_stale_index_when_graph_changed() -> None:
    from company_ontology_agent.retrieval.runtime import _status_with_client

    class StaleClient:
        def query(self, statement, parameters=None):
            if "KnowledgeChunk" in statement:
                return [{"chunk_count": 3}]
            if "SHOW INDEXES" in statement:
                return [{"state": "ONLINE"}]
            if "RagIndexMeta" in statement:
                return [
                    {
                        "indexed_entities": 5,
                        "indexed_assertions": 2,
                        "entity_count": 6,
                        "assertion_count": 2,
                    }
                ]
            return []

    status = _status_with_client(default_config("demo"), StaleClient())

    assert status.ready is True
    assert status.stale is True
    assert "rag index" in status.message


def test_reset_project_is_slug_scoped() -> None:
    client = object.__new__(Neo4jClient)
    calls: list[tuple[str, dict[str, object] | None]] = []
    client.execute = lambda statement, parameters=None: calls.append((statement, parameters))

    client.reset_project("demo")

    assert calls
    assert all(parameters == {"slug": "demo"} for _, parameters in calls)
    assert not any("MATCH (n) DETACH DELETE n" in statement for statement, _ in calls)


def test_sources_api_lists_and_serves_full_text(tmp_path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from company_ontology_agent.api.app import create_app

    class FakeRuntime:
        def list_sources(self, *, limit: int = 500):
            return [
                {
                    "id": "source-1",
                    "path": "docs/guide.md",
                    "source_type": "document",
                    "title": "docs/guide.md",
                    "span_count": 2,
                    "chunk_count": 2,
                }
            ]

        def source_chunks(self, source_id: str, *, limit: int = 500):
            if source_id != "source-1":
                return []
            return [{"span_id": "s1", "start": 0, "end": 10, "text": "Full text.", "ordinal": 0}]

        def close(self) -> None:
            return None

    client = TestClient(create_app(tmp_path, runtime=FakeRuntime()))

    listing = client.get("/api/sources")
    assert listing.status_code == 200
    assert listing.json()["sources"][0]["path"] == "docs/guide.md"
    detail = client.get("/api/sources/source-1")
    assert detail.status_code == 200
    assert detail.json()["chunks"][0]["text"] == "Full text."
    assert client.get("/api/sources/missing").status_code == 404
