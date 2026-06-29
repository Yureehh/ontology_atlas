# Troubleshooting

## `Neo4j credentials are required`

Set:

```bash
export NEO4J_USER=neo4j
export NEO4J_PASSWORD='your-password'
```

Or use:

```bash
ontology-agent build-graph --dry-run
```

## `Connection refused on localhost:7687`

Neo4j is not accepting Bolt connections at the configured URI.

Check:

- Neo4j Desktop database is started.
- Bolt is enabled.
- The configured port is correct.
- `project.yaml` uses the same database name.

## `Graphify executable not found`

This is not fatal unless `graphify.strict` is true.

Reinstall the ontology agent package so `graphifyy[openai,neo4j,pdf]` is installed in the same virtual environment:

```bash
cd /Users/yureeh/Documents/ontology_atlas
uv build
uv tool install --force dist/company_ontology_agent-0.1.0-py3-none-any.whl
```

Then check:

```bash
ontology-agent --help
ontology-agent graphify --help
```

## Empty Wiki

Run graph build first:

```bash
ontology-agent build-graph --dry-run
ontology-agent export-wiki
```

If using Neo4j:

```bash
ontology-agent build-graph
ontology-agent export-wiki --neo4j
```

## Installed CLI Does Not See Source Checkout

For development, use:

```bash
uv sync --extra dev
PYTHONPATH=src uv run ontology-agent --help
```

For a company asset install test, use a UV tool install:

```bash
uv build
uv tool install --force dist/company_ontology_agent-0.1.0-py3-none-any.whl
ontology-agent --help
```

If `ontology-agent` is not found after `uv tool install`, run:

```bash
uv tool update-shell
```

Then restart the terminal.

Direct `graphify --help` is optional. The ontology agent can resolve Graphify from its
installed tool environment. Install Graphify separately only if you want to run the
Graphify CLI by hand:

```bash
uv tool install --force "graphifyy[openai,neo4j,pdf]"
```
