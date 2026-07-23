# Quickstart

## 1. Install The CLI

Recommended install after cloning the repo:

```bash
cd /path/to/ontology_atlas
uv tool install --force '.[rag]'
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
uv tool install --force 'company_ontology_agent-0.1.0-py3-none-any.whl[rag]'
```

For a global CLI using the pip ecosystem:

```bash
pipx install '.[rag]'
```

For package development only:

```bash
uv sync --extra dev --extra rag
uv run --extra dev --extra rag ontology-agent --help
```

Full macOS, Linux, and Windows install notes are in [Install](install.md).

## 2. Create A Project Instance

For a real repository, create the ontology project inside that repository and import a curated source copy:

```bash
ontology-agent init client-atlas \
  --target /path/to/client/.ontology-agent \
  --source /path/to/client \
  --source-profile code-docs \
  --with-docker \
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

## 5. Publish, Index, And Serve

After Neo4j is running, set the Neo4j/OpenAI values in `.env`, then enable the answer layer:

```yaml
llm:
  provider: openai
embedding:
  provider: openai
rag:
  enabled: true
```

Run the complete client-demo path with one command:

```bash
ontology-agent launch
```

It performs one incremental extraction and then publishes, indexes, builds, and serves that exact
graph. Press Ctrl+C to stop the portal. Generated Docker projects can use `make start` to ensure
Neo4j is running first. Use `ontology-agent launch --no-serve` for CI or refresh-only runs.

This is additive and idempotent. It uses stable IDs and Neo4j `MERGE`, so normal code
additions update the graph without deleting previous data. Use `make reset` only
for a clean local demo rebuild after major deletions or renames.

For the normal additive path with safe stale marking after deletes or renames:

`make refresh` uses safe stale marking automatically.

For offline validation without Neo4j or OpenAI:

```bash
make check
```

The portal is written to `portal/index.html` and links to the wiki, Graphify artifacts,
and the curated architecture graph. This path uses the dry-run graph and does not
require Neo4j.

## 6. Direct CLI Equivalent

```bash
ontology-agent launch
ontology-agent launch --no-serve
ontology-agent portal build --dry-run
ontology-agent portal serve
ontology-agent graph verify-visuals --neo4j
```

See `docs/reference/cli.md` for every CLI command and `docs/reference/generated-project.md`
for every generated Make target.

## 7. Serve The Portal

```bash
ontology-agent portal serve --port 8765
```

Then open `http://127.0.0.1:8765/portal/index.html` to use Ask, Explore, Insights,
and Changes. For live answers, publish to Neo4j and run `ontology-agent rag index` first.

## Clean Wheel Smoke Test

This is for release validation, not normal usage:

```bash
uv build
uv tool install --force 'dist/company_ontology_agent-0.1.0-py3-none-any.whl[rag]'
ontology-agent --help
```

Once installed as a UV tool, generated project Makefiles can call `ontology-agent`
directly without `PYTHONPATH`, temporary virtualenvs, or exported command paths.
