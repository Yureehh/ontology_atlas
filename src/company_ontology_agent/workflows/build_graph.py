from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from company_ontology_agent.config.project_config import ProjectConfig, load_project_config
from company_ontology_agent.config.settings import runtime_settings
from company_ontology_agent.extraction.graphify_adapter import GraphifyExtractor
from company_ontology_agent.graph.baseline import write_scope_fingerprint
from company_ontology_agent.graph.models import ExtractedGraph
from company_ontology_agent.graph.neo4j_client import Neo4jClient, Neo4jConnection
from company_ontology_agent.graph.repository import (
    GraphRepository,
    JsonGraphRepository,
    Neo4jGraphRepository,
)
from company_ontology_agent.ingestion.documents import build_document_graph
from company_ontology_agent.ontology.validator import OntologyValidator
from company_ontology_agent.resolution.entity_resolution import EntityResolver
from company_ontology_agent.structured.models import PruneMode
from company_ontology_agent.structured.projection import build_structured_graph
from company_ontology_agent.workflows.projection import build_curated_projection
from company_ontology_agent.workflows.semantic_enrichment import build_semantic_enrichment


class BuildGraphResult(BaseModel):
    graph: ExtractedGraph
    warnings: list[str] = Field(default_factory=list)
    rejected_count: int = 0
    dry_run: bool = False


class ProgressReporter(Protocol):
    def __call__(self, message: str) -> None: ...


def repository_for(
    project_root: Path, config: ProjectConfig, dry_run: bool = False
) -> GraphRepository:
    if dry_run:
        return JsonGraphRepository(project_root / "data" / "processed" / "graph.json")
    settings = runtime_settings(config)
    if not settings.neo4j_user or not settings.neo4j_password:
        raise RuntimeError(
            f"Neo4j credentials are required. Set {config.graph.username_env} and "
            f"{config.graph.password_env}, or rerun with --dry-run."
        )
    client = Neo4jClient(
        Neo4jConnection(
            uri=settings.neo4j_uri,
            username=settings.neo4j_user,
            password=settings.neo4j_password,
            database=settings.neo4j_database,
        )
    )
    return Neo4jGraphRepository(
        client, write_visual_relationships=config.graph.write_visual_relationships
    )


def build_graph(
    project_root: Path | None = None,
    *,
    dry_run: bool = False,
    prune_mode: PruneMode = "none",
    progress: ProgressReporter | None = None,
) -> BuildGraphResult:
    return build_graph_from_graphify(
        project_root,
        dry_run=dry_run,
        prune_mode=prune_mode,
        progress=progress,
    )


def build_graph_from_graphify(
    project_root: Path | None = None,
    *,
    dry_run: bool = False,
    graphify_graph: ExtractedGraph | None = None,
    run_graphify: bool = True,
    replace: bool = False,
    prune_mode: PruneMode = "none",
    progress: ProgressReporter | None = None,
) -> BuildGraphResult:
    root = project_root or Path.cwd()
    config = load_project_config(root)
    graph = ExtractedGraph(project_slug=config.project_slug)
    if graphify_graph is not None:
        _report(
            progress,
            "Using Graphify graph: "
            f"{len(graphify_graph.entities)} entities, "
            f"{len(graphify_graph.assertions)} assertions.",
        )
        graph = graph.merge(graphify_graph)
    elif config.graphify.enabled and run_graphify:
        _report(progress, "Running Graphify extraction from data/raw.")
        graphify = GraphifyExtractor.from_config(root, config)
        extracted = graphify.extract(root / config.graphify.input_path, config.project_slug)
        _report(
            progress,
            f"Graphify extracted {len(extracted.entities)} entities and "
            f"{len(extracted.assertions)} assertions.",
        )
        graph = graph.merge(extracted)

    _report(progress, "Graphify is the sole code and document extraction stage.")

    if config.rag.document_chunks:
        documents = build_document_graph(root, config)
        if documents.sources:
            _report(
                progress,
                f"Ingested {len(documents.sources)} document(s) as "
                f"{len(documents.chunks)} full-text chunk(s).",
            )
        graph = graph.merge(documents)

    if config.extraction.ontology_projection_enabled:
        _report(progress, "Building opt-in ontology projection.")
        curated = build_curated_projection(root, config)
        _report(
            progress,
            f"Ontology projection produced {len(curated.entities)} entities and "
            f"{len(curated.assertions)} assertions.",
        )
        graph = graph.merge(curated)
    else:
        _report(progress, "Skipping hardcoded ontology projection.")

    if config.datasets:
        _report(
            progress,
            f"Building structured dataset graph for {len(config.datasets)} dataset(s).",
        )
    dataset_graph = build_structured_graph(root, config)
    if config.datasets:
        _report(
            progress,
            f"Structured datasets produced {len(dataset_graph.entities)} entities and "
            f"{len(dataset_graph.assertions)} assertions.",
        )
    if config.extraction.semantic_enrichment_enabled:
        enrichment = build_semantic_enrichment(graph, dataset_graph)
        _report(
            progress,
            f"Semantic alignment produced {len(enrichment.assertions)} bounded relationship(s).",
        )
        graph = graph.merge(enrichment)
    graph = graph.merge(dataset_graph)

    _report(
        progress,
        f"Validating graph: {len(graph.entities)} entities, {len(graph.assertions)} assertions.",
    )
    validation = OntologyValidator(root).validate(graph)
    _report(progress, f"Validation rejected {len(validation.rejected)} item(s).")

    _report(progress, "Resolving duplicate entities.")
    resolved_graph, _ = EntityResolver().resolve(validation.graph)
    _report(
        progress,
        f"Resolved graph has {len(resolved_graph.entities)} entities and "
        f"{len(resolved_graph.assertions)} assertions.",
    )

    _report(progress, "Opening graph repository.")
    repository = repository_for(root, config, dry_run=dry_run)
    _report(progress, "Bootstrapping graph constraints/storage.")
    repository.bootstrap()
    local_repository = JsonGraphRepository(root / "data" / "processed" / "graph.json")
    if replace:
        local_repository.bootstrap()
        local_repository.snapshot_previous()
        _report(progress, "Writing canonical local snapshot and comparison fingerprint.")
        local_repository.replace_graph(resolved_graph)
        write_scope_fingerprint(root, config)

    if not isinstance(repository, JsonGraphRepository):
        mode = "local JSON" if dry_run else f"Neo4j upsert with prune={prune_mode}"
        _report(progress, f"Writing graph to {mode}.")
        repository.upsert_graph(resolved_graph, prune_mode=prune_mode)
    _report(progress, "Graph write complete.")

    return BuildGraphResult(
        graph=resolved_graph,
        warnings=graph.warnings,
        rejected_count=len(validation.rejected),
        dry_run=dry_run,
    )


def _report(progress: ProgressReporter | None, message: str) -> None:
    if progress is not None:
        progress(message)
