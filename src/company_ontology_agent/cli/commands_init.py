from __future__ import annotations

from pathlib import Path

import typer

from company_ontology_agent.config.templates import scaffold_project
from company_ontology_agent.ingestion.raw_import import SourceProfile, import_raw_files


def init_project(
    project_slug: str,
    template: str = "graphify-neo4j",
    with_docker: bool = False,
    force: bool = False,
    target: Path | None = None,
    source: Path | None = None,
    source_profile: SourceProfile = "code-docs",
) -> None:
    if template != "graphify-neo4j":
        raise typer.BadParameter("Only the graphify-neo4j template is supported in v1.")
    project_target = target or Path(project_slug)
    target = scaffold_project(
        project_target,
        project_slug,
        with_docker=with_docker,
        force=force,
    )
    typer.echo(f"Initialized ontology project at {target}")
    if source is not None:
        result = import_raw_files(source, target / "data" / "raw", profile=source_profile)
        typer.echo(
            f"Imported {result.copied} files from {result.source_root} "
            f"into {result.target_root} using profile={result.profile} "
            f"(skipped={result.skipped})."
        )
