from typing import Annotated

import typer

from company_ontology_agent.config.project_config import find_project_root, load_project_config
from company_ontology_agent.config.settings import runtime_settings
from company_ontology_agent.extraction.graphify_adapter import (
    GraphifyExtractor,
    apply_community_names,
    parse_graphify_graph,
)
from company_ontology_agent.graph.bootstrap import write_bootstrap_files
from company_ontology_agent.graph.neo4j_client import Neo4jClient, Neo4jConnection
from company_ontology_agent.graph.visuals import summarize_visual_graph
from company_ontology_agent.structured.models import PruneMode
from company_ontology_agent.workflows.build_graph import build_graph, repository_for

graph_app = typer.Typer(help="Graph operations.")
graphify_app = typer.Typer(help="Graphify operations.")


def build_graph_command(
    dry_run: bool = typer.Option(False, "--dry-run"),
    prune: Annotated[PruneMode, typer.Option("--prune")] = "none",
) -> None:
    result = build_graph(
        find_project_root(),
        dry_run=dry_run,
        prune_mode=prune,
        progress=lambda message: typer.echo(f"  - {message}"),
    )
    typer.echo(
        f"Built graph: {len(result.graph.entities)} entities, "
        f"{len(result.graph.assertions)} assertions, rejected={result.rejected_count}"
    )
    for warning in result.warnings:
        typer.echo(f"Warning: {warning}")


@graph_app.command("bootstrap")
def graph_bootstrap(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    root = find_project_root()
    write_bootstrap_files(root)
    config = load_project_config(root)
    repository = repository_for(root, config, dry_run=dry_run)
    repository.bootstrap()
    typer.echo("Graph bootstrap complete.")


@graph_app.command("reset")
def graph_reset(yes: bool = typer.Option(False, "--yes")) -> None:
    if not yes:
        typer.echo("Refusing to reset Neo4j without --yes.")
        raise typer.Exit(code=1)
    root = find_project_root()
    config = load_project_config(root)
    settings = runtime_settings(config)
    if not settings.neo4j_user or not settings.neo4j_password:
        raise RuntimeError(
            f"Neo4j credentials are required. Set {config.graph.username_env} and "
            f"{config.graph.password_env}."
        )
    client = Neo4jClient(
        Neo4jConnection(
            uri=settings.neo4j_uri,
            username=settings.neo4j_user,
            password=settings.neo4j_password,
            database=settings.neo4j_database,
        )
    )
    try:
        client.reset_database()
    finally:
        client.close()
    typer.echo("Neo4j database reset complete.")


@graph_app.command("prune")
def graph_prune(
    mode: Annotated[PruneMode, typer.Option("--mode")] = "stale",
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    if mode == "delete" and not yes:
        typer.echo("Refusing destructive prune without --yes.")
        raise typer.Exit(code=1)
    root = find_project_root()
    config = load_project_config(root)
    current = repository_for(root, config, dry_run=True).read_graph(config.project_slug)
    repository_for(root, config, dry_run=False).prune_graph(current, mode)
    typer.echo(f"Neo4j prune complete: mode={mode}.")


@graph_app.command("verify-visuals")
def graph_verify_visuals(dry_run: bool = typer.Option(True, "--dry-run/--neo4j")) -> None:
    root = find_project_root()
    config = load_project_config(root)
    graph = repository_for(root, config, dry_run=dry_run).read_graph(config.project_slug)
    summary = summarize_visual_graph(graph)
    typer.echo(f"Curated entities: {summary.entity_count}")
    typer.echo(f"Curated visual relationships: {summary.relationship_count}")
    if summary.top_relationships:
        typer.echo(
            "Top relationships: "
            + ", ".join(f"{name}={count}" for name, count in summary.top_relationships)
        )
    if not summary.is_usable:
        typer.echo(
            "No usable curated visual graph found. Run `ontology-agent run --dry-run` "
            "or `ontology-agent run --neo4j` before opening the graph."
        )
        raise typer.Exit(code=1)
    typer.echo(f"Portal: {root / 'portal' / 'data-graph.html'}")
    typer.echo(f"Neo4j queries: {root / 'graph' / 'explore.cypher'}")


@graphify_app.command("run")
def graphify_run() -> None:
    root = find_project_root()
    config = load_project_config(root)
    extractor = GraphifyExtractor.from_config(root, config)
    typer.echo(
        "Running Graphify extraction "
        f"(backend={config.graphify.backend}, mode={config.graphify.mode})."
    )
    result = extractor.run(
        root / config.graphify.input_path,
        config.project_slug,
        progress=lambda message: typer.echo(f"  - {message}"),
    )
    for line in result.summary_lines():
        typer.echo(line)
    if result.graph.warnings:
        typer.echo(f"Report: {result.report_path}")


@graphify_app.command("extract")
def graphify_extract() -> None:
    graphify_run()


@graphify_app.command("cluster")
def graphify_cluster() -> None:
    root = find_project_root()
    config = load_project_config(root)
    extractor = GraphifyExtractor.from_config(root, config)
    result = extractor.cluster(root)
    typer.echo(result.stdout.strip() or "Graphify clustering complete.")
    if result.stderr.strip():
        typer.echo(result.stderr.strip())
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)
    graph_json = root / config.graphify.output_path / "graph.json"
    if config.graphify.auto_name_communities and graph_json.exists():
        graph = apply_community_names(
            parse_graphify_graph(graph_json, config.project_slug),
            root / config.graphify.output_path,
        )
        community_count = len({entity.community for entity in graph.entities if entity.community})
        typer.echo(f"Named Graphify communities: {community_count}")


@graphify_app.command("tree")
def graphify_tree() -> None:
    root = find_project_root()
    config = load_project_config(root)
    extractor = GraphifyExtractor.from_config(root, config)
    result = extractor.tree(root, label=config.project_name)
    typer.echo(result.stdout.strip() or "Graphify tree complete.")
    if result.stderr.strip():
        typer.echo(result.stderr.strip())
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)


@graphify_app.command("query")
def graphify_query(question: str) -> None:
    _graphify_aux("query", question)


@graphify_app.command("explain")
def graphify_explain(node: str) -> None:
    _graphify_aux("explain", node)


@graphify_app.command("path")
def graphify_path(source: str, target: str) -> None:
    _graphify_aux("path", source, target)


def _graphify_aux(command_name: str, *args: str) -> None:
    root = find_project_root()
    config = load_project_config(root)
    extractor = GraphifyExtractor.from_config(root, config)
    result = extractor.run_auxiliary(root, command_name, *args)
    typer.echo(result.stdout.strip())
    if result.stderr.strip():
        typer.echo(result.stderr.strip())
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)
