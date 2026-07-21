# Neo4j GraphRAG

Ontology Atlas uses Neo4j as both the canonical knowledge graph and the semantic retrieval
store. It does not maintain a second client-facing graph or execute user-authored Cypher.

## Indexing

`ontology-agent rag index` reads the canonical graph and creates one deterministic
`KnowledgeChunk` per entity. Each chunk includes:

- the entity description and mapped type,
- incoming and outgoing relationship statements,
- evidence excerpts and source paths,
- generated wiki context, its path, and evidence classification,
- project slug, content hash, embedding model, and source-span IDs.

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
  -> VectorCypherRetriever (project-filtered semantic candidates)
  -> fixed one-to-three-hop entity traversal
  -> source spans, paths, evidence tiers, and scores
  -> evidence-only answer prompt
  -> typed answer with citations and trace ID
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
  top_k: 8
  max_hops: 2
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
report for the Trust page.

## Deliberate boundaries

V1 is local, single-project, and read-only. It does not include Text2Cypher, graph writes from
questions, authentication, tenancy, MCP, or hosted deployment. `portal/graph.json` remains an
offline visualization payload, not the live GraphRAG backend. Graphify's retired `graph.html`
is never a retrieval source.
