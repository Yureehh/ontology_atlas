from __future__ import annotations

from pathlib import Path


def ensure_project_dirs(project_root: Path) -> None:
    for relative in [
        "data/raw",
        "data/structured",
        "data/normalized",
        "data/processed/rejected",
        "ontology/versions",
        "ontology/datasets",
        "graph/migrations",
        "graphify-out",
        "wiki/entities",
        "wiki/decisions",
        "wiki/requirements",
        "wiki/issues",
        "wiki/tasks",
        "wiki/meetings",
        "logs",
        "tests/fixtures",
        "tests/replay",
        "scripts",
    ]:
        (project_root / relative).mkdir(parents=True, exist_ok=True)
