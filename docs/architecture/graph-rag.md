# Neo4j GraphRAG

Ontology Atlas uses Neo4j as both the canonical knowledge graph and the semantic retrieval
store. It does not maintain a second client-facing graph or execute user-authored Cypher.

## Indexing

`ontology-agent rag index` reads the canonical graph and creates compact deterministic summaries:

- architecture summaries per source file/module,
- dataset summaries with source paths, record types, counts, and authority,
- dataset/type summaries,
- a bounded set of high-value architecture entities.

High-volume structured records remain queryable in Neo4j but are not embedded individually.

Neo4j relationships preserve traceability:

```text
(KnowledgeChunk)-[:ABOUT]->(Entity)
(KnowledgeChunk)-[:SUPPORTED_BY]->(SourceSpan)<-[:HAS_SPAN]-(Source)
```

Only new or content-changed chunks are embedded. Missing chunks are removed, and the saved
index status records model, freshness, indexed, unchanged, and deleted counts. The configured
vector dimension must match the provider output.

## Query path

```text
question
  -> exact entity/alias lookup
  -> deterministic parameterized analytics when representable
  -> locally gated, validated Text2Cypher planning for other analytics
  -> VectorCypherRetriever for explanatory/evidence questions
  -> typed answer with citations, paths, analysis metadata, and timings
```

The implementation uses the official `neo4j-graphrag[openai]` package. The default traversal
is two hops and is capped at three. Both the vector filter and the fixed retrieval query require
the active `project_slug`, preventing another project's chunks from entering an answer.

Retrieved text is explicitly treated as untrusted content. The prompt tells the model not to
follow instructions inside evidence, to distinguish authoritative structured facts from
extracted claims, and to refuse when support is missing.

## Configuration

```yaml
graph:
  vector_index_name: chunk_embeddings
embedding:
  provider: openai
  model_env: ONTOLOGY_AGENT_EMBEDDING_MODEL
  dimension: 1536
llm:
  provider: openai
  model_env: ONTOLOGY_AGENT_LLM_MODEL
  api_key_env: OPENAI_API_KEY
rag:
  enabled: true
  top_k: 4
  max_hops: 2
  analytics:
    enabled: true
    text2cypher_local: true
    max_hops: 3
    max_rows: 100
    timeout_seconds: 5
```

The runtime fails clearly when Neo4j credentials, OpenAI credentials, models, the optional
dependency, or vector configuration are unavailable.

## Interfaces

```bash
ontology-agent rag index
ontology-agent rag status
ontology-agent rag ask "Which systems are affected if Customer Profile changes?"
ontology-agent rag evaluate
```

`ontology-agent portal serve` adds the same read-only contract to the local portal:

- `GET /api/rag/status`
- `POST /api/rag/query` with `{ "question": "..." }`

Responses include the answer, trace ID, citations and excerpts, entities, relationship paths,
retrieval scores, evidence tiers, warnings, and timings.

## Evaluation

`rag/questions.yaml` is the project's acceptance suite. Supported questions declare expected
entities and sources; unsupported questions set `should_answer: false`. `rag evaluate` measures
citation validity, retrieval, refusal accuracy, latency, and case-level failures, then saves the
report for review and CI reporting.

## Safe analytical fallback

`Text2CypherRetriever` is used only as a local planner. Atlas rejects writes, procedures, comments,
multi-statements, unknown labels, unscoped entity variables, unbounded/excessive traversals, and
oversized results. It runs `EXPLAIN`, uses read routing with a timeout, verifies zero updates, and
requires citation-bearing rows. This fallback is enabled for loopback `launch` and disabled for
network-exposed serving. Generated-query diagnostics are appended locally to
`rag/text2cypher-diagnostics.jsonl` and are not exposed on the answer page. A Neo4j read-only
account remains recommended.

V1 is local and single-project. It does not include graph writes from questions, authentication,
tenancy, MCP, hosted deployment, or public unrestricted Text2Cypher.
