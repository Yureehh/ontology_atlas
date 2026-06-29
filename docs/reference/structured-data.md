# Structured Data Connectors

V1.1 adds generic structured-data connectors. This lets the suite model business facts
from tables/files alongside code, docs, PDFs, and Graphify/OpenAI extraction.

PDFs and documents are useful semantic evidence. Databases, CSV, JSON, JSONL, Parquet,
and SQL tables are authoritative structured facts and should use connectors plus mappings.

## Supported Connectors

- `csv`
- `json`
- `jsonl`
- `parquet`
- `sqlite`
- `postgres` / `postgresql` / `aurora` interface via `uri_env`

Parquet is optional to keep the base asset lightweight:

```bash
uv tool install --force '.[parquet]'
```

PostgreSQL/Aurora uses an environment variable for the database URL and requires selected
tables in `include_tables`.

## Project Config

```yaml
datasets:
  - name: data_reply_people
    domain: people
    connector: csv
    path: ./data/structured/data_reply/people.csv
    mapping: ./ontology/datasets/data_reply_people.yaml

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

## Mapping Files

Mappings are generic. They define source records, entity identity, display names,
properties, redaction, and relationships.

```yaml
entities:
  person:
    source: people
    type: PersonRecord
    key: person_id
    name: full_name
    properties: [email, title, team_id]
    redact: [email]

relationships:
  - type: REPORTS_TO
    from_entity: person
    from_key: manager_id
    to_entity: person
    to_key: person_id
```

Entity `key` and relationship `from_key` may be a single field or a composite list.
`name` may be a field or a template:

```yaml
entities:
  prediction:
    source: predictions
    type: Prediction
    key: [model_name, record_id]
    name: "{model_name} {record_id}"
```

Connectors also expose metadata fields for mappings:

- `__source`
- `__path`
- `__parent`
- `__grandparent`

`type` and relationship names are mapping-driven. HR, claims, customers, policies,
assets, evaluations, and decisions are all modeled with the same mapping system.

## Commands

```bash
ontology-agent data sample-template data_reply
ontology-agent data inspect
ontology-agent data ingest
ontology-agent data build-graph --dry-run
ontology-agent run --dry-run
ontology-agent run --neo4j
```

If `datasets` are configured in `project.yaml`, high-level `run`, `make check`, and
`make publish` include them automatically.

## Output

Structured records become:

- `BusinessEntity` graph entities with `mapped_type`, `domain`, `dataset`, and connector metadata.
- Canonical assertions with source/evidence metadata.
- Direct visual relationships for Neo4j and the portal.
- `Project -> Domain -> Dataset -> Entity` links in Neo4j.
- `wiki/domains/<domain>.md` and `wiki/datasets/<dataset>.md`.

## Pruning

Publishing is additive by default. To handle deleted or renamed sources:

```bash
ontology-agent run --neo4j --prune stale
ontology-agent graph prune --mode stale
ontology-agent graph prune --mode delete --yes
```

`stale` is the safe default: it marks missing generated graph items as superseded.
`delete` physically removes missing generated items for the current project scope.
