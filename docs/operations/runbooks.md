# Runbooks

This page is the operational checklist for testing a generated ontology project.

## Where Commands Are Documented

- Full CLI reference: `docs/reference/cli.md`
- Generated project folders and Make targets: `docs/reference/generated-project.md`
- Structured data connectors and mappings: `docs/reference/structured-data.md`
- Graphify setup: `docs/getting-started/graphify.md`
- Neo4j Desktop setup and queries: `docs/getting-started/neo4j-desktop.md`

## Graphify-Only Test

Use this when you want to validate extraction and Graphify artifacts without Neo4j.

```bash
cd /path/to/repo/.ontology-agent
ontology-agent doctor
ontology-agent ingest ./data/raw
ontology-agent graphify run
ontology-agent graphify cluster
ontology-agent graphify tree
open graphify-out/GRAPH_TREE.html
open graphify-out/GRAPH_REPORT.md
```

Expected outputs:

```text
graphify-out/graph.json
graphify-out/GRAPH_TREE.html
graphify-out/GRAPH_REPORT.md
```

This path does not write the canonical ontology graph. It validates the Graphify source
graph and supporting reports.

## Local Dry-Run, Wiki, And Portal

Use this as the default no-Neo4j check.

```bash
cd /path/to/repo/.ontology-agent
make check
make portal
make view
```

Expected outputs:

```text
data/normalized/*.jsonl
data/processed/graph.json
data/processed/rejected/summary.md
wiki/index.md
wiki/graph-summary.md
portal/index.html
portal/ask.html
portal/explore.html
portal/intelligence.html
portal/changes.html
portal/trust.html
portal/graph.json
```

`make view` serves the local portal. Without a populated Neo4j GraphRAG index, Ask reports its
readiness state while Explore remains available. `index.html` redirects to Ask.

## Oracle Bets Clean Manager Demo

Use this when preparing a fresh Oracle Bets recording or manager presentation. It
intentionally removes rebuildable generated artifacts and resets the local demo Neo4j
database.

```bash
cd /Users/yureeh/Documents/ontology_atlas
uv tool install --force '.[parquet]'

cd /Users/yureeh/dev/oracle_bets/.ontology-agent
make doctor
ontology-agent data inspect
make clean-generated
make reset-neo4j
make check
make publish-prune
make rag-index
make rag-evaluate
make verify-visuals
make view
```

Expected final outputs:

```text
portal/index.html
portal/ask.html
portal/explore.html
portal/graph.json
wiki/index.html
wiki/architecture.html
wiki/data-graph.html
wiki/graph-summary.html
graphify-out/GRAPH_TREE.html
graphify-out/GRAPH_REPORT.md
graph/explore.cypher
NEO4J_EXPLORE_GUIDE.md
```

The Oracle Bets demo should keep `ontology_projection_enabled: false` and
`local_fallback_enabled: false`. The trusted data story comes from Graphify/OpenAI
source evidence plus explicit Parquet/SQLite dataset mappings.

## Neo4j End-To-End Test

Start Neo4j Desktop first. The default local connection is:

```bash
NEO4J_URI=bolt://localhost:7687
NEO4J_DATABASE=neo4j
NEO4J_USER=neo4j
NEO4J_PASSWORD=<your-password>
```

Then run:

```bash
cd /path/to/repo/.ontology-agent
make doctor
make publish-prune
make verify-visuals
make wiki
```

For a full one-step build after `make doctor`, use:

```bash
ontology-agent run --neo4j --prune stale
```

This runs ingestion, Graphify/OpenAI extraction, automatic community naming, structured
datasets, validation, Neo4j upsert, wiki export, and portal build.

For a clean local POC only:

```bash
make reset-neo4j
make publish
make verify-visuals
```

Do not use `make reset-neo4j` against a shared database.

## Neo4j Demo Queries

Label counts:

```cypher
MATCH (n)
RETURN labels(n) AS labels, count(*) AS count
ORDER BY count DESC;
```

Relationship counts:

```cypher
MATCH ()-[r]->()
RETURN type(r) AS relationship, count(*) AS count
ORDER BY count DESC;
```

Curated visual graph:

```cypher
MATCH p=(a:DemoNode)-[r]->(b:DemoNode)
WHERE NOT a:Source AND NOT b:Source
  AND NOT a:SourceSpan AND NOT b:SourceSpan
  AND NOT a:Assertion AND NOT b:Assertion
  AND NOT a:GraphifyNode AND NOT b:GraphifyNode
  AND NOT a:GraphifyEdge AND NOT b:GraphifyEdge
RETURN p
LIMIT 200;
```

Domain and dataset graph:

```cypher
MATCH p=(:Project)-[:HAS_DOMAIN]->(:Domain)-[:HAS_DATASET]->(:Dataset)-[:HAS_ENTITY]->(:Entity)
RETURN p
LIMIT 200;
```

Stale generated items:

```cypher
MATCH (n {stale: true})
RETURN labels(n) AS labels, n.name AS name, n.id AS id
LIMIT 50;
```

The generated project also includes `graph/explore.cypher` and `NEO4J_EXPLORE_GUIDE.md`.
Use those for demos.

## Structured Data Connector Smoke Test

Create the sample files:

```bash
ontology-agent data sample-template data_reply
```

Add the printed `datasets:` block to `project.yaml`, then run:

```bash
ontology-agent data inspect
ontology-agent data build-graph --dry-run
make check
```

Expected outputs:

```text
data/structured/data_reply/people.csv
ontology/datasets/data_reply_people.yaml
data/processed/structured_inspection.json
wiki/domains/people.md
wiki/datasets/data-reply-people.md
```

## Full Package Gate

Run this before calling a release or demo branch ready:

```bash
uv sync --extra dev
uv run --extra dev pytest
uv run --extra dev ruff check .
uv run --extra dev mypy src/company_ontology_agent
uv run --extra dev mkdocs build --strict
uv build
```

Pre-commit runs the fast local subset:

```bash
uv run --extra dev pre-commit run --all-files
```
