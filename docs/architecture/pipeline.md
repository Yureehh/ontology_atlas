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

`GraphifyExtractor` owns source extraction; structured connectors project directly into the
same `ExtractedGraph` model before validation and resolution.

Current implementations:

- `GraphifyExtractor`: code/document adapter that shells out to `graphify`.
- Structured connectors: authoritative facts from CSV, JSON, JSONL, Parquet, SQLite,
  and PostgreSQL/Aurora-style sources.
- Bounded semantic enrichment: aligns extracted architecture with existing domain
  summaries and adds provenance-backed relationships only.

No second raw-text LLM extraction pass runs over the same files, and semantic enrichment
cannot create row-level business entities.

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
