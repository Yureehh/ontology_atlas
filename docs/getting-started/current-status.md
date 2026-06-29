# Current Status

## What Exists

The repository currently contains a working Python package using a `src/` layout:

```text
src/company_ontology_agent/
tests/
docs/
pyproject.toml
mkdocs.yml
uv.lock
```

The package exposes:

```bash
ontology-agent
```

The command surface includes:

- `init`
- `import-raw`
- `ingest`
- `build-graph`
- `export-wiki`
- `sync`
- `run`
- `full-stack`
- `serve`
- `doctor`
- `graph bootstrap`
- `graph reset`
- `graph prune`
- `graph verify-visuals`
- `graphify run`
- `graphify cluster`
- `graphify tree`
- `graphify query`
- `portal build`
- `portal serve`
- `data inspect`
- `data build-graph`
- `data sample-template`

## What Can Be Used Today

You can use it today for local dry-run projects:

- scaffold a new project,
- import curated code/docs into `data/raw/`,
- add `.txt`, `.md`, `.pdf`, or transcript `.json` files,
- normalize them into JSONL,
- run Graphify/OpenAI extraction,
- map structured CSV, JSON, JSONL, Parquet, SQLite, or PostgreSQL-style datasets,
- validate and resolve the extracted graph,
- persist a canonical dry-run graph snapshot,
- generate a markdown wiki,
- generate a local portal,
- write the canonical graph to local Neo4j Desktop.

## External Dependency Status

Graphify is included as a package dependency. If `graphify` cannot be resolved from
the current environment, the build writes `graphify-out/GRAPH_REPORT.md` and records
a warning unless strict mode is enabled. Demo-quality runs should use Graphify/OpenAI
and structured connectors, not the local fallback.

Neo4j is canonical for real graph writes. If Neo4j credentials are not configured, real
graph writes fail clearly and instruct the user to use `--dry-run`.

The durable verification path is documented in [Runbooks](../operations/runbooks.md).
Use `make check` for local Graphify/wiki/portal validation and `make publish-prune`
for the Neo4j path with safe stale marking.

## Known V1 Limitations

- Deterministic fallback and ontology projection are opt-in debug modes, disabled by default.
- Neo4j integration requires a running database to complete live E2E verification.
- The markdown wiki is generated from graph state and is intended to be committed for review, but not manually treated as canonical truth.
