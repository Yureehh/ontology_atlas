# CLI Reference

This is the canonical guide for available `ontology-agent` commands and what each one
does. For generated ontology projects, the local `Makefile` wraps the most common
commands for daily use.

## `ontology-agent launch`

```bash
ontology-agent launch
ontology-agent launch --no-serve
ontology-agent launch --full
```

This is the primary client workflow. It validates configuration, incrementally extracts code and
documents, loads deterministic business data, validates and resolves one canonical graph,
publishes project-scoped changes to Neo4j, incrementally indexes compact retrieval summaries,
builds the four-page workspace, and serves it on `127.0.0.1`.

`--no-serve` performs the same single build for CI or an offline handoff. `--full` deliberately
re-runs the cost-bearing Graphify extraction. Expert commands below remain useful for diagnosis.

## `ontology-agent init`

```bash
ontology-agent init <project_slug> \
  --template graphify-neo4j \
  --target .ontology-agent \
  --source /path/to/repo \
  --source-profile code-docs \
  --with-docker \
  --force
```

Creates a project instance.

`--target` lets a project live in a hidden or custom folder. `--source` imports a curated source copy into `data/raw/`. The `code-docs` profile excludes secrets, virtualenvs, node modules, caches, generated images, and binary artifacts.

## `ontology-agent run`

```bash
ontology-agent run --dry-run
ontology-agent run --neo4j
ontology-agent run --neo4j --prune stale
ontology-agent run --full          # force full re-extraction (LLM cost)
```

`run --neo4j --prune stale` is the expert publish command used when individual stages need
diagnosis.
It runs Graphify extraction, automatic community naming, structured connectors,
validation, Neo4j writes, wiki export, and portal build.

**Incremental by default.** When a prior Graphify extraction exists, `run` refreshes it
cheaply via `graphify update` (re-extracts only changed code, **no LLM cost**). Pass `--full`
to force a from-scratch re-extraction (e.g. after large document changes). See
[Progressive Updates](../getting-started/progressive-updates.md).

Runs the normal project workflow with progress logs:

```text
[1/3] Checking project
[2/3] Running Graphify
[3/3] Building graph
```

`--dry-run` writes to the local JSON repository and exports wiki markdown from it.
`--neo4j` writes to Neo4j and exports from Neo4j.

Neo4j writes are additive/idempotent. Existing graph records are matched by stable IDs
and updated with Cypher `MERGE`; new records are added. Dry-run mode refreshes the local
JSON validation snapshot.

`--prune stale` marks generated Neo4j nodes/relationships missing from the current graph
as superseded. Use `graph prune --mode delete --yes` only for destructive cleanup.

## `ontology-agent import-raw`

```bash
ontology-agent import-raw /path/to/source-folder
ontology-agent import-raw /path/to/source-folder --profile code-docs --clear
```

Copies source files into `data/raw/`. If the source folder itself contains a `raw/` folder, the command copies the contents of that folder to avoid `data/raw/raw`.

Profiles:

- `code-docs`: code, docs, configs, migrations, and structured text.
- `docs`: markdown, text, PDF, and reStructuredText only.
- `all`: every file except the fixed safety exclusions.

`--clear` replaces the current `data/raw/` contents before importing.

## `ontology-agent build-graph`

```bash
ontology-agent build-graph
ontology-agent build-graph --dry-run
ontology-agent build-graph --prune stale
```

Runs Graphify if enabled, structured extraction, validation, resolution, and graph writes.

Use `--dry-run` when Neo4j is not configured. Dry-run writes to `data/processed/graph.json`.
Use `--prune stale` with Neo4j writes when you want missing generated items marked stale
after source deletions or renames.

## `ontology-agent export-wiki`

```bash
ontology-agent export-wiki
ontology-agent export-wiki --neo4j
```

Exports markdown pages from graph state.

By default this reads the dry-run JSON repository. Use `--neo4j` to read Neo4j.

## `ontology-agent portal`

```bash
ontology-agent portal build --dry-run
ontology-agent portal build --neo4j
ontology-agent portal serve --port 8765
```

Builds or serves the static local demo portal under `portal/`. The build emits sibling
pages that share one renderer: Ask, Explore, Insights, and Changes. Explore filters
one combined graph into All, Architecture, and Business data layers.

`portal serve` binds to `127.0.0.1` by default, serves static project assets, and exposes
the read-only GraphRAG API. Ask requires the server; Explore remains usable through `file://`.
Non-loopback binding is rejected unless `--allow-network` is supplied explicitly.

## `ontology-agent rag`

```bash
ontology-agent rag index
ontology-agent rag status
ontology-agent rag ask "Which systems are affected if Customer Profile changes?"
ontology-agent rag evaluate
```

`index` creates or incrementally updates deterministic `KnowledgeChunk` embeddings in the
configured Neo4j vector index. `status` reports readiness and indexed chunk count. `ask`
returns the same typed JSON contract used by the portal API: answer, trace ID, citations,
entities, paths, evidence tiers, scores, warnings, and timings.

`evaluate` runs `rag/questions.yaml`, reports citation validity, expected-entity/source
relationship retrieval, no-answer refusal, latency, and failures, then saves
`rag/evaluation.json` for review and CI reporting.

## `ontology-agent doctor`

```bash
ontology-agent doctor
ontology-agent doctor --strict
```

Checks project files, ontology files, Graphify, Neo4j credentials/connectivity, LLM
credentials, and—when enabled—GraphRAG configuration and installed dependencies. Docker is
reported as an optional convenience.

`--strict` exits non-zero when required project, credential, or connectivity checks fail.

## `ontology-agent graph bootstrap`

```bash
ontology-agent graph bootstrap
ontology-agent graph bootstrap --dry-run
```

Writes bootstrap files and creates graph constraints through the selected repository.

## `ontology-agent graph reset`

```bash
ontology-agent graph reset --yes
```

Deletes every node and relationship in the configured Neo4j database. This is intended only for local POC resets and requires `--yes`.

You do not need this for normal additions. Use it only when you want to remove stale
nodes after large deletions/renames or when preparing a clean local demo.

## `ontology-agent graph prune`

```bash
ontology-agent graph prune --mode stale
ontology-agent graph prune --mode delete --yes
```

Applies stale handling using the current dry-run graph as the source of truth. `stale`
marks missing generated items; `delete` physically removes them and requires `--yes`.

## `ontology-agent graph verify-visuals`

```bash
ontology-agent graph verify-visuals --dry-run
ontology-agent graph verify-visuals --neo4j
```

Reports curated entity and relationship counts. It exits non-zero when the graph only
contains provenance-style data and is not useful for the client demo.

## `ontology-agent graphify run`

```bash
ontology-agent graphify run
```

Runs the Graphify adapter. If Graphify is missing and strict mode is disabled, it records a report and warning.

Successful runs print a short summary and write a concise `graphify-out/GRAPH_REPORT.md`.

Additional Graphify wrappers:

```bash
ontology-agent graphify extract
ontology-agent graphify cluster
ontology-agent graphify tree
ontology-agent graphify query "What are the main modules?"
ontology-agent graphify explain "Backend"
ontology-agent graphify path "Frontend" "Database"
```

## `ontology-agent data`

```bash
ontology-agent data sample-template data_reply
ontology-agent data inspect
ontology-agent data ingest
ontology-agent data build-graph --dry-run
ontology-agent data build-graph --neo4j
```

Structured data commands inspect configured datasets, write inspection snapshots, build
only the structured graph layer, and generate a Data Reply sample template. High-level
`ontology-agent run` includes configured datasets automatically.
