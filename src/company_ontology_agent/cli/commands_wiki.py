from __future__ import annotations

import typer

from company_ontology_agent.config.project_config import find_project_root, load_project_config
from company_ontology_agent.wiki.exporter import WikiExporter
from company_ontology_agent.workflows.build_graph import repository_for


def export_wiki(dry_run: bool = typer.Option(True, "--dry-run/--neo4j")) -> None:
    root = find_project_root()
    config = load_project_config(root)
    repository = repository_for(root, config, dry_run=dry_run)
    graph = repository.read_graph(config.project_slug)
    files = WikiExporter().export(
        graph,
        root / config.wiki.output_path,
        display_name=config.project_name,
    )
    typer.echo(f"Exported {len(files)} wiki files.")
