# Generated Project

`ontology-agent init manomano-poc --with-docker` creates:

```text
manomano-poc/
├── project.yaml
├── .gitignore
├── .env.example
├── docker-compose.yml
├── README.md
├── Makefile
├── data/
│   ├── raw/
│   ├── structured/
│   └── processed/
├── graphify-out/
├── rag/
│   └── questions.yaml
├── ontology/
│   ├── core.ttl
│   ├── shapes.ttl
│   └── datasets/
├── graph/
│   ├── constraints.cypher
│   └── explore.cypher
├── portal/
├── wiki/
│   ├── entities/
│   ├── decisions/
│   ├── requirements/
│   ├── issues/
│   ├── tasks/
│   ├── domains/
│   ├── datasets/
│   ├── sources/
│   ├── graph-summary.md
│   └── index.md
```

## Ownership

Raw files live under `data/raw/`. For embedded project usage, this is a rebuildable curated copy created by `import-raw`.

Structured CSV, JSON, JSONL, SQLite snapshots, or connector inputs live under `data/structured/`.
They are optional. When configured in `project.yaml`, high-level runs include them
automatically.

Processed graph snapshots and rejection logs live under `data/processed/`.

Ontology governance files live under `ontology/`.

Structured dataset mappings live under `ontology/datasets/`.

Neo4j constraints and optional expert/debug queries live under `graph/`.

Generated wiki pages live under `wiki/` and are intended to be committed.

## Folder Meaning

- `data/raw/`: source documents you want the agent to learn from.
- `data/structured/`: optional structured business data inputs for connector-driven graphs.
- `data/processed/`: local dry-run graph snapshots, validation projections, and rejection logs; rebuildable.
- `ontology/`: project governance files, including SHACL shapes and structured dataset mappings.
- `graph/`: generated Neo4j constraints and expert/debug queries.
- `graphify-out/`: Graphify intermediate output and latest human report.
- `rag/`: golden questions plus rebuildable index/evaluation status.
- `portal/`: generated answer-first workspace; rebuildable and not committed by default.
- `wiki/`: generated markdown knowledge base intended for human review and git commits.

Use `ontology-agent import-raw /path/to/source-folder --profile code-docs --clear` to populate `data/raw/` safely. It avoids accidentally creating nested paths such as `data/raw/raw` and excludes common noisy folders such as `.venv`, `node_modules`, caches, secrets, generated reports, and binary artifacts.

## Daily Commands

Use these first:

```bash
make start       # ensure Neo4j is available; build if needed; serve the portal
make refresh     # rebuild after source or data changes without serving
make stop        # stop the generated Neo4j service
make check       # dry-run graph, wiki, and portal; no Neo4j writes
make evaluate    # run project golden questions
```

For clean local POCs only:

```bash
make reset
make clean-generated
```

## Git Policy

Commit:

- `project.yaml`
- ontology files
- graph bootstrap files
- `Makefile`
- scripts
- README
- `wiki/**/*.md`

Do not commit:

- `.env`
- `data/raw/` when it is imported from another repo
- `data/processed/`
- Graphify cache and dated run folders
- `portal/`
- SQLite metadata
- local Python caches
