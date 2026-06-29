# Roadmap

## V1.1: Local Company Asset

Current scope:

- installable UV package and CLI,
- generated project scaffold,
- safe source import for code, docs, and PDFs,
- Graphify/OpenAI extraction,
- deterministic local fallback,
- SHACL and mapping validation,
- structured data connectors for CSV, JSON, JSONL, SQLite, and PostgreSQL-style URLs,
- mapping-driven business entity graphs,
- additive Neo4j writes with safe stale marking,
- generated wiki,
- generated local portal,
- FastAPI adapter,
- MkDocs documentation,
- GitHub Actions CI and pre-commit checks.

V1.1 is local-first and manager-demo ready. It is not a hosted multi-user platform.

## V1.2: Hardening

Near-term improvements:

- richer structured connector examples,
- stronger stale relationship diff reporting,
- better portal graph layouts for very large graphs,
- optional vector index support when embeddings are configured,
- richer GraphRAG answers over graph neighborhoods and evidence snippets,
- more replay fixtures from real project shapes,
- improved Neo4j Explore styling guidance as Neo4j Desktop evolves.

## V2: Shared Team Service

Goal: a team service wrapping the same core engine.

Required capabilities:

- hardened FastAPI deployment profile,
- authentication,
- project/job metadata store,
- background workers,
- shared Neo4j graph,
- durable job execution,
- richer query API,
- Docker Compose E2E runtime,
- PostgreSQL metadata backend,
- optional object storage,
- observability basics.

Architecture rule:

```text
CLI -> Core Engine
FastAPI -> Core Engine
```

No business logic duplication between CLI and API.

## V3: Enterprise Platform

Goal: enterprise-wide ontology and project-memory platform.

Required capabilities:

- SSO/OIDC,
- RBAC,
- multi-tenancy,
- central graph search,
- cross-project discovery,
- Neo4j Enterprise or Aura Enterprise,
- Kubernetes,
- Helm,
- Terraform,
- enterprise object storage,
- audit logs,
- data classification controls,
- OpenTelemetry,
- Prometheus/Grafana,
- human review and graph governance workflows.

The enterprise platform should wrap the ontology engine rather than replace it.
