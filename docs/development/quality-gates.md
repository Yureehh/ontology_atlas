# Quality Gates

The project uses UV for dependency and command execution.

## Install

```bash
uv sync --extra dev
```

## Tests

```bash
uv run --extra dev pytest
```

## Lint

```bash
uv run --extra dev ruff check .
```

## Type Check

```bash
uv run --extra dev mypy src/company_ontology_agent
```

## Documentation

```bash
uv run --extra dev mkdocs build --strict
```

## Package Build

```bash
uv build
```

## CI

GitHub Actions runs the same commands in `.github/workflows/ci.yml`.

Local shortcut:

```bash
make check
```

## Pre-Commit

Install local hooks with:

```bash
uv run --extra dev pre-commit install
```

The hook runs Ruff, mypy, and pytest. Run the full quality gate, including MkDocs and
`uv build`, before publishing or opening a release PR.

## Clean Wheel Smoke

```bash
uv build
uv tool install --force dist/company_ontology_agent-0.1.0-py3-none-any.whl
ontology-agent --help
```

For pip-based consumers, test inside an activated virtualenv:

```bash
uv venv /tmp/ontology-agent-venv
uv pip install --python /tmp/ontology-agent-venv/bin/python dist/company_ontology_agent-0.1.0-py3-none-any.whl
/tmp/ontology-agent-venv/bin/ontology-agent --help
```

## Release Checklist

Before a release or manager demo, run the full gate above, then validate one generated
project with:

```bash
make check
make publish-prune
make verify-visuals
```

The Neo4j commands require a running local Neo4j Desktop DBMS.
