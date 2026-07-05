# Company Ontology Agent

Company Ontology Agent is a reusable internal asset for creating one ontology instance per project or PoC.

It ingests project artifacts, runs Graphify/OpenAI extraction, projects the result into
a curated ontology, writes a canonical Neo4j graph, and generates a readable wiki plus
a local demo portal.

## Product Intent

The ontology engine is the product. Everything else is an adapter.

```text
CLI (current)  ·  FastAPI / Workers / Hosted (future adapters)
        |
        v
Core ontology engine
```

The current implementation is V1: a local installable package and CLI-first workflow
for manager-demo-ready repository intelligence. It is shaped so later FastAPI, worker,
and hosted deployments can reuse the same core workflows without duplicating business logic.

## Current User Flow

```bash
ontology-agent init slidesmith-poc \
  --target .ontology-agent \
  --source . \
  --source-profile code-docs \
  --with-markdown-wiki \
  --force
cd .ontology-agent
make demo
```

Use `make check` for local validation without writing to Neo4j. Use `make publish-prune`
for the canonical Neo4j graph, safe stale marking, and final wiki. Use `make demo`
when preparing the manager-facing portal and Neo4j exploration pack.

## Documentation Map

- [Quickstart](getting-started/quickstart.md): install, scaffold, ingest, build, and export.
- [Environment](getting-started/environment.md): `.env` and required runtime variables.
- [Graphify](getting-started/graphify.md): Graphify install, command mode, and output handling.
- [OpenAI](getting-started/openai.md): provider setup and structured extraction.
- [Neo4j Desktop](getting-started/neo4j-desktop.md): how to run a real local graph backend.
- [Portal And Wiki](getting-started/portal-and-wiki.md): the generated portal pages and wiki.
- [Progressive Updates](getting-started/progressive-updates.md): incremental re-runs and the Changes diff.
- [Architecture Overview](architecture/overview.md): boundaries and component ownership.
- [Data Model](architecture/data-model.md): assertion-centric graph model.
- [Pipeline](architecture/pipeline.md): source-to-wiki flow.
- [Portal](architecture/portal.md): the portal pages, ranking, search, and exports.
- [Graph Intelligence](architecture/graph-intelligence.md): hotspots, refactor candidates, questions, quality.
- [GraphRAG Readiness](architecture/graph-rag.md): retrieval shape and how to enable semantic search.
- [CLI Reference](reference/cli.md): command contract.
- [Generated Project](reference/generated-project.md): generated folders and Make targets.
- [Structured Data](reference/structured-data.md): connector and mapping reference.
- [Configuration](reference/configuration.md): `project.yaml` fields.
- [Caveats](reference/caveats.md): known limitations and trade-offs.
- [Runbooks](operations/runbooks.md): exact Graphify-only, portal, Neo4j, and structured data tests.
- [Quality Gates](development/quality-gates.md): UV, Ruff, mypy, pytest, MkDocs.
