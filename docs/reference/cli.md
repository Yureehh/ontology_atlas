# CLI Reference

This is the canonical guide for available `ontology-agent` commands and what each one
does. For generated ontology projects, the local `Makefile` wraps the most common
commands for daily use.

## `ontology-agent init`

```bash
ontology-agent init <project_slug> \
  --template graphify-neo4j \
  --target .ontology-agent \
  --source /path/to/repo \
  --source-profile code-docs \
  --with-docker \
  --with-markdown-wiki \
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

`run --neo4j --prune stale` is the recommended one-step manager-demo publish command.
It runs Graphify/OpenAI extraction, automatic community naming, structured connectors,
validation, Neo4j writes, wiki export, and portal build.

**Incremental by default.** When a prior Graphify extraction exists, `run` refreshes it
cheaply via `graphify update` (re-extracts only changed code, **no LLM cost**). Pass `--full`
to force a from-scratch re-extraction (e.g. after large document changes). See
[Progressive Updates](../getting-started/progressive-updates.md).

Runs the normal project workflow with progress logs:

```text
[1/4] Checking project
[2/4] Ingesting data/raw
[3/4] Running Graphify
[4/4] Building graph
```

`--dry-run` writes to the local JSON repository and exports wiki markdown from it.
`--neo4j` writes to Neo4j and exports from Neo4j.

Neo4j writes are additive/idempotent. Existing graph records are matched by stable IDs
and updated with Cypher `MERGE`; new records are added. Dry-run mode refreshes the local
JSON validation snapshot.

`--prune stale` marks generated Neo4j nodes/relationships missing from the current graph
as superseded. Use `graph prune --mode delete --yes` only for destructive cleanup.

## `ontology-agent full-stack`

```bash
ontology-agent full-stack
```

Runs `run --dry-run` first, then `run --neo4j`. Use this when you want one command that validates the local path, writes the canonical Neo4j graph, and exports the final wiki.

## `ontology-agent demo`

```bash
ontology-agent demo
ontology-agent demo --dry-run
```

Runs the manager-demo path and prints the important output locations:

- Neo4j Explore guide,
- generated `graph/explore.cypher`,
- generated portal,
- generated wiki,
- Graphify report.

`--dry-run` skips Neo4j and uses the local JSON graph for the portal and wiki.

## `ontology-agent ingest`

```bash
ontology-agent ingest ./data/raw
```

Normalizes supported files into `data/normalized/*.jsonl`.

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
pages that share one renderer — `index.html` (a redirect to the populated layer),
`data-graph.html` (the connector data graph), `repo.html` (the code/architecture graph),
`intelligence.html` (the Graphify dashboard), and `changes.html` — plus the complete `graph.json`.

## `ontology-agent doctor`

```bash
ontology-agent doctor
ontology-agent doctor --strict
```

Checks project files, ontology files, Graphify availability, Docker availability, Neo4j credentials, and LLM credentials.

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
contains provenance-style data and is not useful for the manager demo.

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
