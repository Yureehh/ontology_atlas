from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

import typer

from company_ontology_agent.cli.commands_data import data_app
from company_ontology_agent.cli.commands_graph import (
    build_graph_command,
    graph_app,
    graphify_app,
)
from company_ontology_agent.cli.commands_ingest import ingest as ingest_command
from company_ontology_agent.cli.commands_init import init_project
from company_ontology_agent.cli.commands_portal import portal_app
from company_ontology_agent.cli.commands_rag import rag_app
from company_ontology_agent.cli.commands_wiki import export_wiki as export_wiki_command
from company_ontology_agent.config.project_config import (
    ProjectConfig,
    find_project_root,
    load_project_config,
)
from company_ontology_agent.config.settings import runtime_settings
from company_ontology_agent.extraction.graphify_adapter import (
    GraphifyExtractor,
    apply_community_names,
    prior_extraction_exists,
    resolve_graphify_executable,
)
from company_ontology_agent.graph.models import ExtractedGraph
from company_ontology_agent.graph.neo4j_client import Neo4jClient, Neo4jConnection
from company_ontology_agent.graph.visuals import summarize_visual_graph
from company_ontology_agent.ingestion.folder import ingest_folder
from company_ontology_agent.ingestion.raw_import import SourceProfile, import_raw_files
from company_ontology_agent.portal.builder import PortalBuilder
from company_ontology_agent.retrieval.questions import FLAGSHIP_QUESTIONS
from company_ontology_agent.retrieval.runtime import ask_project, index_project
from company_ontology_agent.structured.models import PruneMode
from company_ontology_agent.wiki.exporter import WikiExporter
from company_ontology_agent.workflows.build_graph import (
    build_graph_from_graphify,
    repository_for,
)

app = typer.Typer(help="Company Ontology Agent")
app.add_typer(graph_app, name="graph")
app.add_typer(graphify_app, name="graphify")
app.add_typer(portal_app, name="portal")
app.add_typer(data_app, name="data")
app.add_typer(rag_app, name="rag")


@app.command("init")
def init(
    project_slug: str,
    template: Annotated[str, typer.Option("--template")] = "graphify-neo4j",
    with_docker: Annotated[bool, typer.Option("--with-docker")] = False,
    with_markdown_wiki: Annotated[bool, typer.Option("--with-markdown-wiki")] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
    target: Annotated[Path | None, typer.Option("--target")] = None,
    source: Annotated[Path | None, typer.Option("--source")] = None,
    source_profile: Annotated[SourceProfile, typer.Option("--source-profile")] = "code-docs",
) -> None:
    init_project(
        project_slug,
        template,
        with_docker,
        with_markdown_wiki,
        force,
        target,
        source,
        source_profile,
    )


@app.command("ingest")
def ingest(path: Path) -> None:
    ingest_command(path)


@app.command("import-raw")
def import_raw(
    source: Path,
    profile: Annotated[SourceProfile, typer.Option("--profile")] = "code-docs",
    clear: Annotated[bool, typer.Option("--clear")] = False,
) -> None:
    root = find_project_root()
    target = root / "data" / "raw"
    result = import_raw_files(source, target, profile=profile, clear=clear)
    typer.echo(
        f"Imported {result.copied} files from {result.source_root} into {result.target_root} "
        f"using profile={result.profile} (skipped={result.skipped})."
    )
    if result.examples:
        typer.echo("Examples: " + ", ".join(str(path) for path in result.examples))


@app.command("build-graph")
def build_graph(
    dry_run: bool = typer.Option(False, "--dry-run"),
    prune: Annotated[PruneMode, typer.Option("--prune")] = "none",
) -> None:
    build_graph_command(dry_run, prune)


@app.command("run")
def run_pipeline(
    dry_run: bool = typer.Option(True, "--dry-run/--neo4j"),
    export_wiki: bool = typer.Option(True, "--export-wiki/--no-export-wiki"),
    prune: Annotated[PruneMode, typer.Option("--prune")] = "none",
    full: bool = typer.Option(
        False,
        "--full",
        help="Force a full Graphify re-extraction (LLM cost) instead of cheap incremental update.",
    ),
) -> None:
    _run_pipeline(dry_run=dry_run, export_wiki=export_wiki, prune=prune, full=full)


@app.command("full-stack")
def full_stack() -> None:
    typer.echo("== Dry-run validation ==")
    _run_pipeline(dry_run=True, export_wiki=True, prune="none")
    typer.echo("== Neo4j sync ==")
    _run_pipeline(dry_run=False, export_wiki=True, prune="none")


@app.command("demo")
def demo(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    root = find_project_root()
    config = load_project_config(root)
    typer.echo("== Manager demo build ==")
    typer.echo("[1/6] Dry-run validation")
    _run_pipeline(dry_run=True, export_wiki=True, prune="none")
    if dry_run:
        typer.echo("[2/6] Neo4j publish skipped (--dry-run)")
    else:
        typer.echo("[2/6] Neo4j publish")
        _run_pipeline(dry_run=False, export_wiki=True, prune="none")
    if not dry_run and config.rag.enabled:
        typer.echo("[3/6] Indexing GraphRAG knowledge")
        index_project(root)
    else:
        reason = "--dry-run" if dry_run else "rag.enabled is false"
        typer.echo(f"[3/6] GraphRAG indexing skipped ({reason})")
    typer.echo("[4/6] Building portal")
    graph = repository_for(root, config, dry_run=dry_run).read_graph(config.project_slug)
    portal_files = PortalBuilder().build(
        graph,
        root,
        root / "portal",
        display_name=config.project_name,
    )
    typer.echo(f"Built portal files: {len(portal_files)}")
    typer.echo("[5/6] Flagship questions")
    if not dry_run and config.rag.enabled:
        for question in FLAGSHIP_QUESTIONS:
            answer = ask_project(root, question)
            typer.echo(f"Q: {question}\nA: {answer.answer}")
    else:
        for question in FLAGSHIP_QUESTIONS:
            typer.echo(f"- {question}")
    typer.echo("[6/6] Outputs")
    typer.echo(f"Portal: {root / 'portal' / 'index.html'}")
    typer.echo(f"Wiki: {root / config.wiki.output_path / 'index.md'}")
    typer.echo(f"Graphify report: {root / config.graphify.output_path / 'GRAPH_REPORT.md'}")


@app.command("export-wiki")
def export_wiki(dry_run: bool = typer.Option(True, "--dry-run/--neo4j")) -> None:
    export_wiki_command(dry_run)


@app.command("doctor")
def doctor(strict: bool = typer.Option(False, "--strict")) -> None:
    root = find_project_root()
    config = load_project_config(root)
    checks = _doctor_checks(config, strict=strict)
    for name, ok in checks.items():
        typer.echo(f"{'OK' if ok else 'WARN'} {name}")
    if strict and not _strict_required_checks_pass(checks):
        raise typer.Exit(code=1)


def _run_pipeline(
    *, dry_run: bool, export_wiki: bool, prune: PruneMode, full: bool = False
) -> None:
    root = find_project_root()
    config = load_project_config(root)

    typer.echo("[1/4] Checking project")
    _print_doctor_checks(config, strict=not dry_run)

    typer.echo("[2/4] Ingesting data/raw")
    normalized: list[Path] = []
    for source in config.sources:
        if source.enabled and source.type == "folder":
            normalized.extend(ingest_folder(root / source.path, root))
    typer.echo(f"Normalized files: {len(normalized)}")
    if not normalized and config.graphify.enabled:
        typer.echo(
            "Warning: no source files were normalized — Graphify will produce an empty graph. "
            f"Populate {config.graphify.input_path} with source files "
            "(for docs/notes use `--source-profile docs` at init)."
        )

    typer.echo("[3/4] Running Graphify")
    graphify_graph = None
    if config.graphify.enabled:
        extractor = GraphifyExtractor.from_config(root, config)
        graphify_input = root / config.graphify.input_path
        graphify_out = root / config.graphify.output_path
        incremental = (
            not full and config.graphify.update and prior_extraction_exists(graphify_out)
        )
        mode_label = (
            "incremental update (no LLM)" if incremental else f"mode={config.graphify.mode}"
        )
        typer.echo(
            f"Graphify input: {graphify_input} (backend={config.graphify.backend}, {mode_label})"
        )
        def progress(message: str) -> None:
            typer.echo(f"  - {message}")

        if incremental:
            graphify_result = extractor.incremental_update(
                graphify_input, config.project_slug, progress=progress
            )
        else:
            graphify_result = extractor.run(graphify_input, config.project_slug, progress=progress)
        graphify_graph = graphify_result.graph
        for line in graphify_result.summary_lines():
            typer.echo(line)
        if graphify_result.exit_code == 0:
            cluster = extractor.cluster(root)
            if cluster.returncode == 0:
                typer.echo("Graphify cluster/report refresh complete.")
                if config.graphify.auto_name_communities and graphify_graph is not None:
                    graphify_graph = apply_community_names(
                        graphify_graph, root / config.graphify.output_path
                    )
                    typer.echo("Graphify community names refreshed.")
            else:
                typer.echo("Warning: Graphify cluster refresh failed.")
            tree = extractor.tree(root, label=config.project_name)
            if tree.returncode == 0:
                typer.echo("Graphify tree artifact complete.")
            else:
                typer.echo("Warning: Graphify tree artifact failed.")
        else:
            typer.echo(
                f"Warning: Graphify FAILED (exit={graphify_result.exit_code}); the graph will be "
                f"empty. See {graphify_out / 'GRAPH_REPORT.md'} — the usual cause is a missing "
                "OPENAI_API_KEY (set it in .env or the shell), then re-run."
            )
    else:
        typer.echo("Graphify disabled.")

    typer.echo("[4/4] Building graph")
    result = build_graph_from_graphify(
        root,
        dry_run=dry_run,
        graphify_graph=graphify_graph,
        run_graphify=False,
        replace=True,
        prune_mode="none" if dry_run else prune,
        progress=lambda message: typer.echo(f"  - {message}"),
    )
    typer.echo(
        f"Built graph: {len(result.graph.entities)} entities, "
        f"{len(result.graph.assertions)} assertions, rejected={result.rejected_count}"
    )
    if dry_run:
        typer.echo("Graph write mode: local validation snapshot refreshed.")
    else:
        typer.echo(f"Graph write mode: additive Neo4j upsert with prune={prune}.")
    for line in _graph_summary_lines(result.graph):
        typer.echo(line)
    rejection_summary = root / "data" / "processed" / "rejected" / "summary.md"
    if rejection_summary.exists():
        typer.echo(f"Validation summary: {rejection_summary}")
    for warning in result.warnings:
        typer.echo(f"Warning: {warning}")

    if export_wiki:
        repository = repository_for(root, config, dry_run=dry_run)
        typer.echo("Reading graph for wiki and portal export.")
        graph = repository.read_graph(config.project_slug)
        typer.echo(f"Exporting wiki to {root / config.wiki.output_path}.")
        files = WikiExporter().export(
            graph,
            root / config.wiki.output_path,
            display_name=config.project_name,
        )
        typer.echo(f"Exported wiki files: {len(files)}")
        typer.echo(f"Building portal at {root / 'portal'}.")
        portal_files = PortalBuilder().build(
            graph,
            root,
            root / "portal",
            display_name=config.project_name,
        )
        typer.echo(f"Built portal files: {len(portal_files)}")
        _print_visual_output_summary(graph, root, dry_run=dry_run)


def _print_doctor_checks(config: ProjectConfig, *, strict: bool) -> None:
    checks = _doctor_checks(config, strict=strict)
    for name, ok in checks.items():
        typer.echo(f"{'OK' if ok else 'WARN'} {name}")
    if strict and not _strict_required_checks_pass(checks):
        raise typer.Exit(code=1)


def _doctor_checks(config: ProjectConfig, *, strict: bool) -> dict[str, bool]:
    root = find_project_root()
    settings = runtime_settings(config)
    graphify_available = resolve_graphify_executable() is not None or not config.graphify.enabled
    neo4j_credentials = bool(settings.neo4j_user and settings.neo4j_password)
    llm_credentials = (
        bool(settings.llm_api_key and settings.llm_model) or config.llm.provider == "local"
    )
    # Graphify shells out with its own backend; when that backend is openai it needs the key
    # in the environment. Surface a missing key here instead of failing mid-extraction.
    graphify_credentials = (
        config.graphify.backend != "openai" or not config.graphify.enabled
    ) or bool(settings.llm_api_key)
    checks = {
        "project.yaml": (root / "project.yaml").exists(),
        ".env": (root / ".env").exists(),
        "ontology core": (root / config.ontology.core_path).exists(),
        "ontology shapes": (root / config.ontology.shapes_path).exists(),
        "raw sources": any((root / source.path).rglob("*") for source in config.sources),
        "no nested data/raw/raw": not (root / "data" / "raw" / "raw").exists(),
        "graphify report freshness": _graphify_report_is_fresh(root),
        "graphify": graphify_available,
        "docker compose": shutil.which("docker") is not None,
        "neo4j credentials": neo4j_credentials,
        "llm credentials": llm_credentials,
        "graphify credentials": graphify_credentials,
    }
    if strict and neo4j_credentials:
        checks["neo4j connectivity"] = _neo4j_connects(config)
    elif strict:
        checks["neo4j connectivity"] = False
    return checks


def _graphify_report_is_fresh(root: Path) -> bool:
    graph_json = root / "graphify-out" / "graph.json"
    report = root / "graphify-out" / "GRAPH_REPORT.md"
    if not graph_json.exists() and not report.exists():
        return True
    if graph_json.exists() and report.exists():
        return report.stat().st_mtime >= graph_json.stat().st_mtime
    return False


def _strict_required_checks_pass(checks: dict[str, bool]) -> bool:
    required = {
        "project.yaml",
        ".env",
        "ontology core",
        "ontology shapes",
        "raw sources",
        "no nested data/raw/raw",
        "graphify",
        "neo4j credentials",
        "llm credentials",
        "neo4j connectivity",
    }
    return all(checks.get(name, False) for name in required)


def _graph_summary_lines(graph: ExtractedGraph) -> list[str]:
    entity_counts: dict[str, int] = {}
    predicate_counts: dict[str, int] = {}
    for entity in graph.entities:
        entity_counts[entity.type.value] = entity_counts.get(entity.type.value, 0) + 1
    for assertion in graph.assertions:
        predicate_counts[assertion.predicate] = predicate_counts.get(assertion.predicate, 0) + 1
    entity_text = ", ".join(f"{name}={count}" for name, count in sorted(entity_counts.items()))
    predicate_text = ", ".join(
        f"{name}={count}" for name, count in sorted(predicate_counts.items())
    )
    lines = []
    if entity_text:
        lines.append(f"Entities by type: {entity_text}")
    if predicate_text:
        lines.append(f"Assertions by predicate: {predicate_text}")
    return lines


def _print_visual_output_summary(graph: ExtractedGraph, root: Path, *, dry_run: bool) -> None:
    summary = summarize_visual_graph(graph)
    typer.echo(f"Curated visual relationships: {summary.relationship_count}")
    if summary.top_relationships:
        typer.echo(
            "Top visual relationships: "
            + ", ".join(f"{name}={count}" for name, count in summary.top_relationships)
        )
    typer.echo(f"Portal: {root / 'portal' / 'index.html'}")
    if dry_run:
        typer.echo("Neo4j skipped: inspect the graph through the portal or Graphify artifacts.")
    else:
        typer.echo(f"Neo4j queries: {root / 'graph' / 'explore.cypher'}")
        typer.echo("If Neo4j shows only Source dots, run query 1 from graph/explore.cypher.")


def _neo4j_connects(config: ProjectConfig) -> bool:
    settings = runtime_settings(config)
    if not settings.neo4j_user or not settings.neo4j_password:
        return False
    client = Neo4jClient(
        Neo4jConnection(
            uri=settings.neo4j_uri,
            username=settings.neo4j_user,
            password=settings.neo4j_password,
            database=settings.neo4j_database,
        )
    )
    try:
        client.verify()
    except Exception:
        return False
    finally:
        client.close()
    return True


if __name__ == "__main__":
    app()
