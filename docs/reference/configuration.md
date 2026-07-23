# Configuration

Each generated project uses `project.yaml` as its central configuration.

## Important Fields

```yaml
project_slug: manomano-poc
project_name: ManoMano POC Ontology
```

## Graph

```yaml
graph:
  uri: bolt://localhost:7687
  uri_env: NEO4J_URI
  database: neo4j
  database_env: NEO4J_DATABASE
  username_env: NEO4J_USER
  password_env: NEO4J_PASSWORD
  vector_index_name: chunk_embeddings
  write_visual_relationships: true
```

Credentials are read from environment variables. They are not stored in `project.yaml`.

`write_visual_relationships` keeps canonical `Assertion` nodes and also writes derived
entity-to-entity relationships for Neo4j Explore. The Neo4j writer also adds `DemoNode`
labels, `caption` properties, and direct `DemoProject -> DemoNode` links so a useful
Explore scene can be opened by clicking the `DemoNode` category even before running a
custom Cypher query.

## Graphify

```yaml
graphify:
  enabled: true
  input_path: ./data/raw
  output_path: ./graphify-out
  backend: openai
  mode: deep
  update: true
  no_viz: false
  strict: false
```

`update: true` enables the cheap incremental path: when a prior extraction exists, `run` calls
`graphify update` (re-extracts only changed code, no LLM cost) instead of a full `extract`.
Set it to `false`, or pass `run --full`, to always re-extract from scratch. See
[Progressive Updates](../getting-started/progressive-updates.md).

## LLM

```yaml
llm:
  provider: local
  model_env: ONTOLOGY_AGENT_LLM_MODEL
  api_key_env: OPENAI_API_KEY
```

Use `provider: openai` with `OPENAI_API_KEY` and `ONTOLOGY_AGENT_LLM_MODEL` for structured extraction. Use `provider: local` for deterministic fallback extraction.

## Embedding and GraphRAG

```yaml
embedding:
  provider: openai
  model_env: ONTOLOGY_AGENT_EMBEDDING_MODEL
  dimension: 1536
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

`top_k` controls semantic candidates. `max_hops` controls the fixed graph neighborhood and
is capped at three. The model output dimension must match `embedding.dimension`. GraphRAG v1
requires OpenAI plus the optional `rag` package extra. Deterministic analytics uses fixed,
parameterized query shapes. `text2cypher_local` enables the validated expert fallback only on a
loopback server; exposing the portal to a network disables it automatically.

Unknown configuration keys are rejected with a migration message instead of being silently ignored.

## Ontology

```yaml
ontology:
  core_path: ./ontology/core.ttl
  shapes_path: ./ontology/shapes.ttl
```

## Wiki

```yaml
wiki:
  output_path: ./wiki
```

## Structured Datasets

```yaml
datasets:
  - name: data_reply_people
    domain: people
    connector: csv
    path: ./data/structured/data_reply/people.csv
    mapping: ./ontology/datasets/data_reply_people.yaml
    enabled: true

  - name: data_reply_events
    domain: operations
    connector: jsonl
    path: ./data/structured/data_reply/events.jsonl
    mapping: ./ontology/datasets/data_reply_events.yaml

  - name: data_reply_predictions
    domain: operations
    connector: parquet
    path: ./data/structured/data_reply/predictions.parquet
    mapping: ./ontology/datasets/data_reply_predictions.yaml
    row_limit: 50000
    required_columns: [record_id, prediction]
```

Datasets are optional. When configured, `ontology-agent launch`, `ontology-agent run`, and
`make check` process them automatically. Mappings are domain-agnostic and can model
people, claims, customers, assets, policies, decisions, evaluations, or any other
structured business data.

PostgreSQL/Aurora-style datasets use `uri_env` and `include_tables`:

```yaml
datasets:
  - name: data_reply_operational_db
    domain: operations
    connector: postgres
    uri_env: DATA_REPLY_DATABASE_URL
    include_tables: [events, decisions]
    mapping: ./ontology/datasets/data_reply_operational_db.yaml
```

## Extraction Defaults

Graphify and structured connectors are the product-quality extraction path. The optional
ontology projection remains an expert debug mode:

```yaml
extraction:
  ontology_projection_enabled: false
```

Set `llm.provider: openai` with `OPENAI_API_KEY` and `ONTOLOGY_AGENT_LLM_MODEL` for
Graphify semantic extraction and GraphRAG answer generation.
