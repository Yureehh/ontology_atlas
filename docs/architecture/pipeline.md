# Pipeline

## Flow

```text
Sources
  ↓
Normalization
  ↓
Graphify/OpenAI source graph
  ↓
Curated ontology projection
  ↓
Ontology validation
  ↓
Entity resolution
  ↓
Graph repository
  ↓              ↓
Neo4j graph     Wiki + portal
```

## Normalization

Ingestion converts supported source files into normalized JSONL records. Each record includes:

- stable source ID,
- source path,
- source type,
- title,
- text,
- SHA-256 hash.

## Extraction

The extraction interface is `KGExtractor`.

Current implementations:

- `GraphifyExtractor`: primary demo-quality adapter that shells out to `graphify`.
- `LLMStructuredExtractor`: OpenAI structured extraction when `llm.provider=openai`.
- Structured connectors: authoritative facts from CSV, JSON, JSONL, Parquet, SQLite,
  and PostgreSQL/Aurora-style sources.

Deterministic local fallback and ontology projection are opt-in debug modes. They are
disabled by default because hardcoded technology/module heuristics do not scale as a
real company asset.

## Validation

Validation checks:

- entity type is known,
- predicate is known,
- assertion subject/object entities exist,
- evidence span exists,
- confidence is above threshold.

Rejected items are persisted under:

```text
data/processed/rejected/
```

## Resolution

V1 entity resolution uses normalized name and type. It avoids aggressive merging.

## Graph Writes

The graph repository interface supports:

- `JsonGraphRepository` for dry-run local use and tests,
- `Neo4jGraphRepository` for canonical graph writes.

Neo4j writes two useful layers:

- canonical assertion/provenance nodes,
- derived entity-to-entity relationships for immediate Explore browsing.

## Wiki Export

The wiki exporter reads graph data and generates synthesized markdown pages. Markdown is a generated companion layer, not the canonical store.

The portal builder reads the same graph and writes `portal/index.html` plus `portal/graph.json`.
