# CI/CD

V1 includes a GitHub Actions workflow:

```text
.github/workflows/ci.yml
```

## Quality Job

The quality job runs:

```bash
uv sync --extra dev --extra rag
uv run --extra dev --extra rag pytest
uv run --extra dev --extra rag ruff check .
uv run --extra dev --extra rag mypy src/company_ontology_agent
uv run --extra dev --extra rag python -m mkdocs build --strict
uv build
```

## Neo4j Integration Job

The workflow also defines a Neo4j service-container job for tests marked:

```python
@pytest.mark.neo4j
```

Local Neo4j Desktop remains the recommended manual V1 E2E target.

## Local Equivalent

From the repository root:

```bash
uv sync --extra dev --extra rag
uv run --extra dev --extra rag pytest
uv run --extra dev --extra rag ruff check .
uv run --extra dev --extra rag mypy src/company_ontology_agent
uv run --extra dev --extra rag mkdocs build --strict
uv build
```

## Documentation Publishing

MkDocs writes generated HTML to `site/`. The folder is ignored locally and should not
be committed. Publish documentation by building from source docs in a GitHub Pages
workflow or by using `gh-pages`.
