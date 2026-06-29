# Configuration

Each generated project uses `project.yaml` as its central configuration.

## Important Fields

```yaml
project_slug: manomano-poc
project_name: ManoMano POC Ontology
environment: local
```

## Runtime

```yaml
runtime:
  backend: local
  metadata_store: sqlite
  raw_store: local_filesystem
```

## Graph

```yaml
graph:
  backend: neo4j
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
  no_viz: true
  export_neo4j_cypher: true
  push_to_neo4j: false
  strict: false
```

`push_to_neo4j` defaults to false because Graphify output is intermediate, not canonical.

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
  extraction_mode: strict_json_schema
```

Use `provider: openai` with `OPENAI_API_KEY` and `ONTOLOGY_AGENT_LLM_MODEL` for structured extraction. Use `provider: local` for deterministic fallback extraction.

## Ontology

```yaml
ontology:
  version: 0.1.0
  core_path: ./ontology/core.ttl
  shapes_path: ./ontology/shapes.ttl
  mappings_path: ./ontology/mappings.yaml
  validation_mode: strict
```

## Wiki

```yaml
wiki:
  enabled: true
  output_path: ./wiki
  format: markdown
  include_frontmatter: true
```

## Sources

```yaml
sources:
  - name: local_docs
    type: folder
    path: ./data/raw
    enabled: true
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

Datasets are optional. When configured, `ontology-agent run`, `make check`, and
`make publish` process them automatically. Mappings are domain-agnostic and can model
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

Graphify/OpenAI and structured connectors are the product-quality extraction path.
Local deterministic fallback and ontology projection are opt-in debug modes:

```yaml
extraction:
  ontology_projection_enabled: false
  local_fallback_enabled: false
```

Set `llm.provider: openai` with `OPENAI_API_KEY` and `ONTOLOGY_AGENT_LLM_MODEL` for
OpenAI structured extraction. Set `local_fallback_enabled: true` only when you
explicitly want offline heuristic extraction.
