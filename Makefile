SHELL := /bin/bash

.PHONY: install install-wheel check test lint typecheck docs build clean

install:
	uv tool install --force .

install-wheel: build
	uv tool install --force dist/company_ontology_agent-0.1.0-py3-none-any.whl

check:
	uv sync --extra dev
	uv run --extra dev pytest
	uv run --extra dev ruff check .
	uv run --extra dev mypy src/company_ontology_agent
	uv run --extra dev mkdocs build --strict
	uv build

test:
	uv run --extra dev pytest

lint:
	uv run --extra dev ruff check .

typecheck:
	uv run --extra dev mypy src/company_ontology_agent

docs:
	uv run --extra dev mkdocs serve

build:
	uv build

clean:
	rm -rf site dist
