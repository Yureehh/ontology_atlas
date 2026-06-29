from __future__ import annotations

import json

import typer

from company_ontology_agent.config.project_config import find_project_root, load_project_config
from company_ontology_agent.structured.projection import (
    build_structured_graph,
    inspect_configured_datasets,
)
from company_ontology_agent.workflows.build_graph import repository_for

data_app = typer.Typer(help="Structured data connector operations.")


@data_app.command("inspect")
def data_inspect() -> None:
    root = find_project_root()
    config = load_project_config(root)
    inspections = inspect_configured_datasets(root, config)
    if not inspections:
        typer.echo("No datasets configured.")
        return
    for inspection in inspections:
        typer.echo(
            f"{inspection.name} domain={inspection.domain} "
            f"connector={inspection.connector}"
        )
        for source, count in inspection.sources.items():
            typer.echo(f"  {source}: {count} records")
            columns = inspection.columns.get(source, [])
            if columns:
                typer.echo(f"    columns: {', '.join(columns[:24])}")


@data_app.command("ingest")
def data_ingest() -> None:
    root = find_project_root()
    config = load_project_config(root)
    output = root / "data" / "processed" / "structured_datasets.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = [inspection.model_dump() for inspection in inspect_configured_datasets(root, config)]
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    typer.echo(f"Wrote {output}")


@data_app.command("build-graph")
def data_build_graph(dry_run: bool = typer.Option(True, "--dry-run/--neo4j")) -> None:
    root = find_project_root()
    config = load_project_config(root)
    graph = build_structured_graph(root, config)
    repository = repository_for(root, config, dry_run=dry_run)
    repository.bootstrap()
    repository.upsert_graph(graph)
    typer.echo(
        f"Built structured graph: {len(graph.entities)} entities, "
        f"{len(graph.assertions)} assertions."
    )


@data_app.command("sample-template")
def data_sample_template(name: str = "data_reply") -> None:
    root = find_project_root()
    data_dir = root / "data" / "structured" / name
    mapping_dir = root / "ontology" / "datasets"
    data_dir.mkdir(parents=True, exist_ok=True)
    mapping_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "people.csv").write_text(
        "person_id,full_name,email,title,team_id,manager_id\n"
        "p1,Ada Rossi,ada.rossi@example.com,Lead Consultant,t1,\n"
        "p2,Luca Bianchi,luca.bianchi@example.com,Data Engineer,t1,p1\n",
        encoding="utf-8",
    )
    (mapping_dir / f"{name}_people.yaml").write_text(
        "entities:\n"
        "  person:\n"
        "    source: people\n"
        "    type: PersonRecord\n"
        "    key: person_id\n"
        "    name: full_name\n"
        "    properties: [email, title, team_id]\n"
        "    redact: [email]\n"
        "relationships:\n"
        "  - type: REPORTS_TO\n"
        "    from_entity: person\n"
        "    from_key: manager_id\n"
        "    to_entity: person\n"
        "    to_key: person_id\n",
        encoding="utf-8",
    )
    typer.echo("Sample dataset written.")
    typer.echo(
        "Add this to project.yaml datasets:\n"
        f"- name: {name}_people\n"
        "  domain: people\n"
        "  connector: csv\n"
        f"  path: ./data/structured/{name}/people.csv\n"
        f"  mapping: ./ontology/datasets/{name}_people.yaml"
    )
