from __future__ import annotations

from pathlib import Path

import typer

from company_ontology_agent.config.project_config import find_project_root
from company_ontology_agent.ingestion.folder import ingest_folder


def ingest(path: Path) -> None:
    root = find_project_root()
    target = path if path.is_absolute() else root / path
    outputs = ingest_folder(target, root)
    if not outputs:
        typer.echo("No supported files found.")
        return
    for output in outputs:
        typer.echo(f"Wrote {output}")
