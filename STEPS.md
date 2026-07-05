# What `ontology-agent` does, step by step

Exact sequence for a full **`ontology-agent run`** (entry: `cli/main.py::run_pipeline` → `_run_pipeline`).
`--dry-run` (default) writes a local snapshot; `--neo4j` upserts to Neo4j.

1. **Locate project** — `config.project_config.find_project_root()` walks up for `project.yaml`.
   → in: cwd · out: project root.
2. **Load config + env** — `config.project_config.load_project_config(root)` calls `load_env_file(root)`
   (parses `.env` into `os.environ` so the graphify subprocess inherits `OPENAI_API_KEY`), then parses
   `project.yaml` → `ProjectConfig`.
3. **Preflight (`[1/4]`)** — `_print_doctor_checks` runs `_doctor_checks`: project files, ontology core/shapes,
   graphify on PATH, LLM + graphify credentials, etc. In `--neo4j` mode a failing required check exits 1.
4. **Ingest (`[2/4]`)** — for each enabled `folder` source: `ingestion.ingest_folder(root/path, root)` →
   `normalizer.normalize_file` per file (`.md/.txt/.pdf/.json`; unreadable files are skipped+logged) →
   `write_jsonl` to `data/normalized/`. Warns if 0 files normalized while graphify is enabled.
5. **Graphify extract (`[3/4]`)** — `GraphifyExtractor.from_config(...)`. Incremental if
   `not --full and config.graphify.update and prior_extraction_exists(...)`, else full.
   `run()`/`incremental_update()` shells `graphify extract <data/raw> --backend … --mode … [--no-viz]`
   (subprocess, heartbeat + completion watch), then `parse_graphify_graph()` → `ExtractedGraph`.
   On exit 0: `cluster()` + `tree()` + `apply_community_names()`. On non-zero exit: a prominent warning
   (usual cause: missing `OPENAI_API_KEY`).
   → writes `graphify-out/` (see ARTIFACTS.md).
6. **Build + validate graph (`[4/4]`)** — `workflows.build_graph.build_graph_from_graphify(root, dry_run,
   graphify_graph=…, run_graphify=False, replace=True, prune_mode=…)`: validates against ontology
   shapes/predicates, rejects invalid items, resolves duplicate entities, then writes.
   `--dry-run` → local snapshot `data/processed/graph.json`; `--neo4j` → additive upsert (+ prune).
   Rejections → `data/processed/rejected/summary.md`.
7. **Export wiki + portal** (when `--export-wiki`, default on) — `repository.read_graph()` reloads the graph,
   then `wiki.exporter.WikiExporter().export()` writes `wiki/**`, and `portal.builder.PortalBuilder().build()`
   writes `portal/**` + `portal/graph.json`.

## `ontology-agent full-stack`
`_run_pipeline(dry_run=True)` (validate) then `_run_pipeline(dry_run=False)` (Neo4j sync) — steps 1–7 twice.

## `ontology-agent init <slug> --source <path> [--source-profile docs|code-docs|all]`
`cli/commands_init` scaffolds the project and `ingestion.raw_import.import_raw_files()` copies matching
source files into `data/raw/` (docs profile = `.md/.txt/.pdf/.rst/.mdx`; no git repo required).
