from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from company_ontology_agent.config.project_config import ProjectConfig
from company_ontology_agent.graph.models import (
    Assertion,
    Entity,
    EntityType,
    ExtractedGraph,
    Source,
    SourceSpan,
)
from company_ontology_agent.utils.hashing import file_hash, stable_hash
from company_ontology_agent.utils.ids import slugify, stable_id


@dataclass(frozen=True)
class DetectedFact:
    subject: Entity
    predicate: str
    object: Entity
    evidence: str
    source_path: str
    confidence: float = 0.86
    tier: str = "generated"


TECH_HINTS = {
    "FastAPI": ["fastapi", "APIRouter", "FastAPI("],
    "OpenAI": ["openai", "OpenAI", "OPENAI_API_KEY"],
    "React": ["react", "React", "tsx"],
    "TypeScript": ["typescript", ".tsx", ".ts"],
    "Vite": ["vite", "vite.config"],
    "Docker": ["Dockerfile", "docker-compose"],
    "PostgreSQL": ["postgresql", "psycopg2", "DATABASE_URL"],
    "SQLAlchemy": ["sqlalchemy", "declarative_base", "Column("],
    "Alembic": ["alembic", "versions/"],
    "pgvector": ["pgvector"],
    "S3": ["boto3", "S3", "S3_BUCKET"],
    "AWS": ["AWS", "ECS", "Fargate", "Aurora", "S3"],
    "Aurora": ["Aurora", "aurora"],
    "ECS": ["ECS", "Fargate"],
    "uvicorn": ["uvicorn"],
}


def build_curated_projection(
    project_root: Path, config: ProjectConfig, base_graph: ExtractedGraph
) -> ExtractedGraph:
    raw_root = project_root / "data" / "raw"
    if not raw_root.exists():
        return ExtractedGraph(project_slug=config.project_slug)

    source_files = sorted(path for path in raw_root.rglob("*") if path.is_file())
    entities: dict[str, Entity] = {}
    sources: dict[str, Source] = {}
    spans: dict[str, SourceSpan] = {}
    facts: list[DetectedFact] = []

    def entity(entity_type: EntityType, name: str, **metadata: str) -> Entity:
        clean_name = " ".join(name.split())
        normalized = slugify(clean_name).replace("-", " ")
        item = Entity(
            id=stable_id("entity", normalized, entity_type.value),
            type=entity_type,
            name=clean_name,
            normalized_name=normalized,
            extraction_source="ontology_projection",
            confidence_tier="generated",
            metadata=metadata,
        )
        entities.setdefault(item.id, item)
        return entities[item.id]

    project = entity(EntityType.system, config.project_name)
    overview = entity(EntityType.system, "Architecture Overview")
    backend = entity(EntityType.module, "Backend")
    frontend = entity(EntityType.module, "Frontend")
    data_layer = entity(EntityType.module, "Data Layer")
    deployment = entity(EntityType.deployment_unit, "Deployment")

    facts.extend(
        [
            DetectedFact(project, "contains", overview, "Project architecture entrypoint.", ""),
            DetectedFact(overview, "contains", backend, "Backend architecture section.", ""),
            DetectedFact(overview, "contains", frontend, "Frontend architecture section.", ""),
            DetectedFact(overview, "contains", data_layer, "Data architecture section.", ""),
            DetectedFact(overview, "contains", deployment, "Deployment architecture section.", ""),
        ]
    )

    file_texts: list[tuple[Path, str]] = []
    for path in source_files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        relative = path.relative_to(raw_root)
        file_texts.append((relative, text[:120_000]))

        source = _source_for(path, raw_root)
        sources[source.id] = source
        file_entity = entity(EntityType.file, str(relative), source_path=str(relative))
        parent = _module_for_path(relative, backend, frontend, data_layer, deployment)
        facts.append(
            DetectedFact(
                parent,
                "contains",
                file_entity,
                f"{relative} belongs to {parent.name}.",
                str(relative),
            )
        )

        for class_name in re.findall(r"^class\s+([A-Z][A-Za-z0-9_]+)", text, flags=re.MULTILINE):
            entity_type = (
                EntityType.data_model if _looks_like_model(class_name, text) else EntityType.class_
            )
            class_entity = entity(entity_type, class_name, source_path=str(relative))
            facts.append(
                DetectedFact(
                    file_entity,
                    "defines",
                    class_entity,
                    f"`{class_name}` is defined in {relative}.",
                    str(relative),
                )
            )
            if entity_type == EntityType.data_model:
                facts.append(
                    DetectedFact(
                        data_layer,
                        "contains",
                        class_entity,
                        f"`{class_name}` is a data model.",
                        str(relative),
                    )
                )

        for function_name in re.findall(
            r"^(?:async\s+def|def)\s+([a-zA-Z_][A-Za-z0-9_]*)",
            text,
            flags=re.MULTILINE,
        ):
            if function_name.startswith("_"):
                continue
            function = entity(EntityType.function, function_name, source_path=str(relative))
            facts.append(
                DetectedFact(
                    file_entity,
                    "defines",
                    function,
                    f"`{function_name}` is defined in {relative}.",
                    str(relative),
                    0.78,
                )
            )

        for method, route in re.findall(
            r"@(?:app|router)\.(get|post|put|patch|delete)\(\s*[\"']([^\"']+)",
            text,
        ):
            endpoint = entity(
                EntityType.api_endpoint, f"{method.upper()} {route}", source_path=str(relative)
            )
            facts.append(
                DetectedFact(
                    backend,
                    "exposes",
                    endpoint,
                    f"`{method.upper()} {route}` is declared in {relative}.",
                    str(relative),
                )
            )
            facts.append(
                DetectedFact(
                    file_entity,
                    "defines",
                    endpoint,
                    f"`{method.upper()} {route}` is declared in {relative}.",
                    str(relative),
                )
            )

    corpus = "\n".join(f"{path}\n{text[:20_000]}" for path, text in file_texts)
    technologies = []
    for tech, hints in TECH_HINTS.items():
        if any(hint in corpus for hint in hints):
            tech_entity = entity(EntityType.technology, tech)
            technologies.append(tech_entity)
            target = _technology_owner(tech, backend, frontend, data_layer, deployment)
            facts.append(
                DetectedFact(
                    target, "uses", tech_entity, f"{tech} is detected in the source corpus.", ""
                )
            )

    _add_cross_layer_relationships(facts, backend, frontend, data_layer, deployment, technologies)

    assertions: list[Assertion] = []
    for index, fact in enumerate(facts):
        source = (
            _source_for(raw_root / fact.source_path, raw_root)
            if fact.source_path
            else _synthetic_source(project_root)
        )
        sources[source.id] = source
        span_id = stable_id("span", "projection", fact.source_path, stable_hash(fact.evidence))
        spans[span_id] = SourceSpan(
            id=span_id,
            source_id=source.id,
            text=fact.evidence,
            start=0,
            end=len(fact.evidence),
        )
        assertions.append(
            Assertion(
                id=stable_id(
                    "assertion", fact.subject.id, fact.predicate, fact.object.id, span_id, index
                ),
                predicate=fact.predicate,
                subject_id=fact.subject.id,
                object_id=fact.object.id,
                evidence_span_id=span_id,
                confidence=fact.confidence,
                extractor="ontology_projection",
                extraction_source="ontology_projection",
                confidence_tier=fact.tier,
                evidence_text=fact.evidence,
                source_path=fact.source_path or None,
            )
        )

    return ExtractedGraph(
        project_slug=config.project_slug,
        sources=list(sources.values()),
        source_spans=list(spans.values()),
        entities=list(entities.values()),
        assertions=assertions,
    )


def _source_for(path: Path, raw_root: Path) -> Source:
    if path.exists() and path.is_file():
        relative = path.relative_to(raw_root)
        sha = file_hash(path)
        title = relative.name
    else:
        relative = Path(str(path))
        sha = stable_hash(str(relative))
        title = relative.name or "Ontology Projection"
    return Source(
        id=stable_id("source", str(relative), sha),
        path=f"data/raw/{relative}",
        source_type="repo_file",
        sha256=sha,
        title=title,
    )


def _synthetic_source(project_root: Path) -> Source:
    return Source(
        id=stable_id("source", "ontology-projection", str(project_root)),
        path="ontology-projection",
        source_type="ontology_projection",
        sha256=stable_hash(str(project_root)),
        title="Ontology projection",
    )


def _module_for_path(
    path: Path,
    backend: Entity,
    frontend: Entity,
    data_layer: Entity,
    deployment: Entity,
) -> Entity:
    text = str(path)
    if text.startswith("frontend/"):
        return frontend
    if text.startswith("alembic/") or "db/" in text or "models/" in text:
        return data_layer
    if (
        text.startswith("Dockerfile")
        or text.startswith("docker-compose")
        or text.startswith("infra/")
    ):
        return deployment
    return backend


def _looks_like_model(class_name: str, text: str) -> bool:
    return (
        "BaseModel" in text
        or "sqlalchemy" in text.lower()
        or class_name.endswith(("Model", "Report", "Slide", "Client", "Session"))
    )


def _technology_owner(
    tech: str,
    backend: Entity,
    frontend: Entity,
    data_layer: Entity,
    deployment: Entity,
) -> Entity:
    if tech in {"React", "TypeScript", "Vite"}:
        return frontend
    if tech in {"PostgreSQL", "SQLAlchemy", "Alembic", "pgvector"}:
        return data_layer
    if tech in {"Docker", "AWS", "Aurora", "ECS", "S3"}:
        return deployment
    return backend


def _add_cross_layer_relationships(
    facts: list[DetectedFact],
    backend: Entity,
    frontend: Entity,
    data_layer: Entity,
    deployment: Entity,
    technologies: list[Entity],
) -> None:
    tech_by_name = {tech.name: tech for tech in technologies}
    facts.extend(
        [
            DetectedFact(frontend, "depends_on", backend, "Frontend calls backend APIs.", ""),
            DetectedFact(backend, "reads_from", data_layer, "Backend reads application data.", ""),
            DetectedFact(backend, "writes_to", data_layer, "Backend writes application data.", ""),
            DetectedFact(
                deployment, "deploys_to", backend, "Deployment runs backend services.", ""
            ),
            DetectedFact(
                deployment, "deploys_to", frontend, "Deployment serves frontend assets.", ""
            ),
        ]
    )
    if "FastAPI" in tech_by_name and "uvicorn" in tech_by_name:
        facts.append(
            DetectedFact(
                tech_by_name["uvicorn"],
                "runs_on",
                tech_by_name["FastAPI"],
                "uvicorn serves FastAPI application code.",
                "",
            )
        )
    if "SQLAlchemy" in tech_by_name and "PostgreSQL" in tech_by_name:
        facts.append(
            DetectedFact(
                tech_by_name["SQLAlchemy"],
                "writes_to",
                tech_by_name["PostgreSQL"],
                "SQLAlchemy is used with PostgreSQL.",
                "",
            )
        )
