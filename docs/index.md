# Ontology Atlas

Ontology Atlas is a reusable enterprise knowledge and impact-analysis accelerator.

It turns code, documents, and business data into cited answers, explorable impact paths,
and measurable trust over one canonical Neo4j graph.

## Product Intent

Trusted answers are the product promise. The ontology engine remains the reusable core.

```text
CLI + local read-only API  ·  Hosted adapters (future)
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
  --force
cd .ontology-agent
make start
```

Use `make check` for local validation without writing to Neo4j. Use `make refresh` after source
or data changes and `make evaluate` to run the project-specific retrieval suite.

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
- [Neo4j GraphRAG](architecture/graph-rag.md): indexing, retrieval, trust, and safety.
- [CLI Reference](reference/cli.md): command contract.
- [Generated Project](reference/generated-project.md): generated folders and Make targets.
- [Structured Data](reference/structured-data.md): connector and mapping reference.
- [Configuration](reference/configuration.md): `project.yaml` fields.
- [Caveats](reference/caveats.md): known limitations and trade-offs.
- [Runbooks](operations/runbooks.md): exact Graphify-only, portal, Neo4j, and structured data tests.
- [Quality Gates](development/quality-gates.md): UV, Ruff, mypy, pytest, MkDocs.
