# Three Scheduled Releases

## V1: Local Project Asset

Goal: one local installable ontology instance per project or PoC.

Required capabilities:

- UV package and wheel build.
- CLI-first workflow.
- Project scaffolding.
- Local ingestion and normalization.
- Graphify intermediate extraction.
- Optional OpenAI structured extraction.
- Generic structured data connectors and mapping-driven business graphs.
- SHACL/OWL/RDF ontology governance.
- Conservative entity resolution.
- Neo4j Desktop canonical graph writes with safe stale marking.
- Generated markdown wiki.
- Generated local portal.
- Dry-run JSON graph for local demos.
- MkDocs documentation.
- GitHub Actions CI.
- Replay fixtures and idempotency tests.

Out of scope:

- authentication,
- multi-tenancy,
- hosted service operations,
- enterprise RBAC,
- Kubernetes.

## V2: Shared Team Service

Goal: a shared service wrapping the same core engine.

Required capabilities:

- hardened FastAPI service,
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
CLI
  -> Core Engine
FastAPI
  -> Core Engine
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

The V3 platform should wrap the ontology engine rather than replace it.
