SHELL := /bin/bash

.PHONY: install install-wheel check test lint typecheck docs build clean

install:
	uv tool install --force '.[rag]'

install-wheel: build
	uv tool install --force 'dist/company_ontology_agent-0.1.0-py3-none-any.whl[rag]'

check:
	uv sync --extra dev --extra rag
	uv run --extra dev --extra rag pytest
	uv run --extra dev --extra rag ruff check .
	uv run --extra dev --extra rag mypy src/company_ontology_agent
	uv run --extra dev --extra rag python -m mkdocs build --strict
	uv build

test:
	uv run --extra dev --extra rag pytest

lint:
	uv run --extra dev --extra rag ruff check .

typecheck:
	uv run --extra dev --extra rag mypy src/company_ontology_agent

docs:
	uv run --extra dev --extra rag python -m mkdocs serve

build:
	uv build

clean:
	rm -rf site dist
