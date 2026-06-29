# Architecture Overview

## Boundary Rule

The ontology engine is the product. Adapters call the engine.

```text
Adapters
  CLI (shipped)
  FastAPI / workers / hosted (future)
  Docker (local Neo4j support)
        |
        v
Core engine
  ingestion
  extraction
  validation
  resolution
  graph writes
  wiki export
  retrieval
```

The core engine must not depend on FastAPI, Docker, or UI code.

## Current Package Layout

```text
src/company_ontology_agent/
├── cli/
├── api/
├── config/
├── ingestion/
├── extraction/
├── ontology/
├── resolution/
├── graph/
├── retrieval/
├── wiki/
├── workflows/
├── storage/
└── utils/
```

## Adapter Responsibilities

The CLI parses command-line intent and calls workflow functions. It is the only adapter
shipped today.

A future FastAPI adapter (not currently shipped) would parse HTTP requests and call the same
workflow functions — the core engine is deliberately kept independent of any web framework so
such an adapter can be added without duplicating business logic.

Docker Compose is generated as runtime support for local Neo4j. It does not define business logic.

## Core Responsibilities

The core engine handles:

- supported source normalization,
- graph candidate extraction,
- Pydantic validation,
- ontology/mapping checks,
- entity resolution,
- graph repository writes,
- wiki export,
- lightweight retrieval.

## Future Evolution

Stage 2 can add a shared FastAPI service, authentication, and workers by reusing the existing workflows.

Stage 3 can add SSO, RBAC, tenancy, Kubernetes, and enterprise graph infrastructure without changing the core engine contract.
