# Quickstart

## 1. Install The CLI

Recommended install after cloning the repo:

```bash
cd /Users/yureeh/Documents/ontology_atlas
uv tool install --force .
ontology-agent --help
```

Equivalent local shortcut:

```bash
make install
```

If UV warns that `~/.local/bin` is not on `PATH`, run this once and restart the shell:

```bash
uv tool update-shell
```

For a wheel or GitLab artifact:

```bash
uv tool install --force company_ontology_agent-0.1.0-py3-none-any.whl
```

For a global CLI using the pip ecosystem:

```bash
pipx install .
```

For package development only:

```bash
uv sync --extra dev
uv run --extra dev ontology-agent --help
```

Full macOS, Linux, and Windows install notes are in [Install](install.md).

## 2. Create A Project Instance

For a real repository, create the ontology project inside that repository and import a curated source copy:

```bash
ontology-agent init ontology-atlas-oracle-bets \
  --target /Users/yureeh/dev/oracle_bets/.ontology-agent \
  --source /Users/yureeh/dev/oracle_bets \
  --source-profile code-docs \
  --with-markdown-wiki
```

This creates:

```text
.ontology-agent/
├── project.yaml
├── .gitignore
├── .env.example
├── docker-compose.yml
├── Makefile
├── data/
├── ontology/
├── graph/
├── graphify-out/
├── wiki/
├── logs/
├── tests/
└── scripts/
```

## 3. Add Source Files

Put supported files in:

```text
.ontology-agent/data/raw/
```

For real repos, prefer the import command instead of copying by hand:

```bash
ontology-agent import-raw /path/to/repo --profile code-docs --clear
```

The `code-docs` profile keeps code, markdown, configs, migrations, and structured docs while excluding secrets, virtualenvs, node modules, caches, local AI/editor state, generated images, and binary artifacts.

## 4. Run A Local Check

From inside the generated project, use the Makefile. It loads `.env` automatically:

```bash
make check
```

This runs doctor checks, ingestion, Graphify, graph build, wiki export, and portal
build through the local JSON repository. A successful run looks like:

```bash
[1/4] Checking project
[2/4] Ingesting data/raw
[3/4] Running Graphify
[4/4] Building graph
Built graph: 267 entities, 49 assertions, rejected=167
Exported wiki files: 120
Built portal files: portal/index.html, portal/graph.json
```

The rejection count is not automatically a failure. It means validation filtered candidate assertions.

## 5. Write To Neo4j

After Neo4j Desktop is running and `.env` contains credentials:

```bash
make publish
```

This is additive and idempotent. It uses stable IDs and Neo4j `MERGE`, so normal code
additions update the graph without deleting previous data. Use `make reset-neo4j` only
for a clean local demo rebuild after major deletions or renames.

For the normal additive path with safe stale marking after deletes or renames:

```bash
make publish-prune
```

## 6. Build The Portal

```bash
make portal
make view
```

The portal is written to `portal/index.html` and links to the wiki, Graphify artifacts,
and the curated architecture graph. This path uses the dry-run graph and does not
require Neo4j.

## 7. Full Demo

```bash
make demo-dry-run
make demo
```

Use `make demo-dry-run` for a full local visual demo without Neo4j. Use `make demo`
when Neo4j is configured and you want the canonical graph published too.

## 8. Export The Wiki

```bash
make wiki
```

The project-local `wiki/` folder is intended to be committed.

## 9. Direct CLI Equivalent

```bash
ontology-agent run --dry-run
ontology-agent run --neo4j
ontology-agent demo --dry-run
ontology-agent demo
ontology-agent portal build --dry-run
ontology-agent portal serve
ontology-agent graph verify-visuals --neo4j
```

Compatibility targets remain available:

```bash
make dry-run
make sync-neo4j
make full-stack
```

See `docs/reference/cli.md` for every CLI command and `docs/reference/generated-project.md`
for every generated Make target.

## 10. Serve The Portal

```bash
ontology-agent portal serve --port 8765
```

Then open `http://127.0.0.1:8765/portal/index.html` to use Ask, Explore, Insights,
Changes, and Trust. For live answers, publish to Neo4j and run `ontology-agent rag index` first.

## Clean Wheel Smoke Test

This is for release validation, not normal usage:

```bash
uv build
uv tool install --force dist/company_ontology_agent-0.1.0-py3-none-any.whl
ontology-agent --help
```

Once installed as a UV tool, generated project Makefiles can call `ontology-agent`
directly without `PYTHONPATH`, temporary virtualenvs, or exported command paths.
