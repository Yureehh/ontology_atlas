from __future__ import annotations

from pathlib import Path


def ensure_project_dirs(project_root: Path) -> None:
    for relative in [
        "data/raw",
        "data/structured",
        "data/processed/rejected",
        "ontology/datasets",
        "graphify-out",
        "rag",
        "wiki/entities",
        "wiki/decisions",
        "wiki/requirements",
        "wiki/issues",
        "wiki/tasks",
    ]:
        (project_root / relative).mkdir(parents=True, exist_ok=True)
