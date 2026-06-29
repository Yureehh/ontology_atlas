# SlideSmith POC Runbook

This runbook creates a hidden ontology project inside SlideSmith:

```text
/Users/yureeh/dev/slidesmith/.ontology-agent
```

## 1. Install The Agent

From the ontology agent repo:

```bash
cd /Users/yureeh/Documents/ontology_atlas
uv tool install --force .
```

Use the installed command:

```bash
ontology-agent --help
```

## 2. Create The Hidden Project

```bash
ontology-agent init slidesmith-poc \
  --target /Users/yureeh/dev/slidesmith/.ontology-agent \
  --source /Users/yureeh/dev/slidesmith \
  --source-profile code-docs \
  --with-markdown-wiki \
  --force
```

The import keeps backend code, frontend source, configs, migrations, and docs. It excludes `.env`, `.venv`, `frontend/node_modules`, local AI/editor state, caches, generated reports, images, and binary templates.

The imported `data/raw/` copy is rebuildable and ignored by git. Commit the ontology config, governance files, scripts, and generated `wiki/**/*.md`; do not commit `.env`, `data/raw/`, `data/normalized/`, or `data/processed/`.

## 3. Configure Environment

Create `/Users/yureeh/dev/slidesmith/.ontology-agent/.env`:

```bash
OPENAI_API_KEY=...
ONTOLOGY_AGENT_LLM_MODEL=...

NEO4J_URI=bolt://localhost:7687
NEO4J_DATABASE=neo4j
NEO4J_USER=neo4j
NEO4J_PASSWORD=...
```

Neo4j Desktop must be running with Bolt enabled on `localhost:7687`.

## 4. Run The POC

```bash
cd /Users/yureeh/dev/slidesmith/.ontology-agent
make doctor
make check
make reset-neo4j
make demo
```

`make check` is local-only. `make demo` runs Graphify/OpenAI extraction, ontology
projection, validation, Neo4j publish, wiki export, and portal build.

## 5. Expected Outputs

- `wiki/index.md`: project overview.
- `wiki/architecture.md`: curated backend/frontend/data/deployment view.
- `wiki/graph-summary.md`: counts, predicates, sources, and validation summary.
- `wiki/graph-rag.md`: retrieval and reasoning readiness.
- `wiki/manager-demo.md`: suggested demo path.
- `portal/index.html`: local manager demo portal.
- `graph/explore.cypher`: ready-made Neo4j demo queries.
- `NEO4J_EXPLORE_GUIDE.md`: Neo4j caption and Explore guidance.
- `wiki/entities/*.md`: entity pages with relationships and evidence.
- `wiki/sources/*.md`: source document pages.
- Neo4j canonical nodes for `Project`, `Source`, `SourceSpan`, `Chunk`, `Entity`, and `Assertion`.
- Neo4j visual entity-to-entity relationships such as `USES`, `DEPENDS_ON`, `EXPOSES`, `DEFINES`, `READS_FROM`, and `WRITES_TO`.
- Graphify artifacts under `graphify-out/`.

## 6. Demo Queries

Open `graph/explore.cypher` and run query 1 first. It hides `Source`, `SourceSpan`,
and `Assertion` nodes so the visual graph shows curated project relationships.

Sanity checks:

```cypher
MATCH (n) RETURN labels(n) AS labels, count(*) AS count ORDER BY count DESC;
```

```cypher
MATCH ()-[r]->() RETURN type(r) AS relationship, count(*) AS count ORDER BY count DESC;
```

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

## Troubleshooting

If Neo4j Explore shows only one project node, run:

```cypher
MATCH (n) RETURN labels(n), count(*) ORDER BY count(*) DESC
```

If entities exist but are hard to browse, search for `Entity` in Explore or run:

```cypher
MATCH (a:Entity)-[r]->(b:Entity)
RETURN a, r, b
LIMIT 100
```

If Graphify reports zero files, verify `data/raw/` contains code and docs and re-run:

```bash
ontology-agent import-raw /Users/yureeh/dev/slidesmith --profile code-docs --clear
make demo
```
