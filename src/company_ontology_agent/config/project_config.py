from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GraphConfig(ConfigModel):
    uri: str = "bolt://localhost:7687"
    uri_env: str = "NEO4J_URI"
    database: str = "neo4j"
    database_env: str = "NEO4J_DATABASE"
    username_env: str = "NEO4J_USER"
    password_env: str = "NEO4J_PASSWORD"
    vector_index_name: str = "chunk_embeddings"
    write_visual_relationships: bool = True


class GraphifyConfig(ConfigModel):
    enabled: bool = True
    input_path: str = "./data/raw"
    output_path: str = "./graphify-out"
    backend: str = "openai"
    mode: Literal["default", "deep"] = "deep"
    update: bool = True
    no_viz: bool = False
    strict: bool = False
    timeout_seconds: int | None = None
    auto_name_communities: bool = True


class LLMConfig(ConfigModel):
    provider: str = "local"
    model_env: str = "ONTOLOGY_AGENT_LLM_MODEL"
    api_key_env: str = "OPENAI_API_KEY"


class EmbeddingConfig(ConfigModel):
    provider: str = "none"
    model_env: str = "ONTOLOGY_AGENT_EMBEDDING_MODEL"
    dimension: int = 1536


class AnalyticsConfig(ConfigModel):
    enabled: bool = True
    text2cypher_local: bool = True
    max_hops: int = Field(default=3, ge=1, le=3)
    max_rows: int = Field(default=100, ge=1, le=500)
    timeout_seconds: float = Field(default=5.0, ge=0.1, le=30.0)


class RagConfig(ConfigModel):
    enabled: bool = False
    top_k: int = Field(default=4, ge=1, le=50)
    max_hops: int = Field(default=2, ge=1, le=3)
    # Most-connected architecture entities that get a dedicated retrieval chunk.
    entity_chunk_limit: int = Field(default=200, ge=1, le=2000)
    # Entity type names to index; empty means the built-in default set.
    entity_chunk_types: list[str] = Field(default_factory=list)
    # Ingest document full text (md/rst/txt) into Neo4j and embed it for retrieval.
    document_chunks: bool = True
    document_chunk_chars: int = Field(default=2000, ge=200, le=8000)
    document_chunk_limit: int = Field(default=1500, ge=1, le=20000)
    analytics: AnalyticsConfig = Field(default_factory=AnalyticsConfig)


class ExtractionConfig(ConfigModel):
    semantic_enrichment_enabled: bool = True
    ontology_projection_enabled: bool = False


class OntologyConfig(ConfigModel):
    core_path: str = "./ontology/core.ttl"
    shapes_path: str = "./ontology/shapes.ttl"


class WikiConfig(ConfigModel):
    output_path: str = "./wiki"


class DatasetConfig(ConfigModel):
    name: str
    domain: str
    connector: str
    mapping: str
    path: str = ""
    uri_env: str = ""
    include_tables: list[str] = Field(default_factory=list)
    row_limit: int | None = None
    required_columns: list[str] = Field(default_factory=list)
    enabled: bool = True


class ProjectConfig(ConfigModel):
    project_slug: str
    project_name: str
    graph: GraphConfig = Field(default_factory=GraphConfig)
    graphify: GraphifyConfig = Field(default_factory=GraphifyConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    rag: RagConfig = Field(default_factory=RagConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    ontology: OntologyConfig = Field(default_factory=OntologyConfig)
    wiki: WikiConfig = Field(default_factory=WikiConfig)
    datasets: list[DatasetConfig] = Field(default_factory=list)


def default_config(project_slug: str) -> ProjectConfig:
    name = project_slug.replace("-", " ").replace("_", " ").title()
    return ProjectConfig(project_slug=project_slug, project_name=f"{name} Ontology")


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "project.yaml").exists():
            return candidate
    raise FileNotFoundError("project.yaml not found in current directory or parents")


def load_env_file(project_root: Path) -> None:
    """Load ``project_root/.env`` into os.environ (shell values take precedence).

    The tool shells out to graphify, which reads credentials (e.g. OPENAI_API_KEY)
    from its own environment. Without this, a key present only in ``.env`` is invisible
    to the subprocess and extraction silently produces an empty graph.
    """
    env_path = project_root / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_project_config(root: Path | None = None) -> ProjectConfig:
    project_root = root or find_project_root()
    load_env_file(project_root)
    with (project_root / "project.yaml").open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    try:
        return ProjectConfig.model_validate(data)
    except ValidationError as exc:
        unknown = [
            ".".join(str(part) for part in error["loc"])
            for error in exc.errors()
            if error["type"] == "extra_forbidden"
        ]
        if unknown:
            raise ValueError(
                "Unsupported project.yaml settings: "
                f"{', '.join(unknown)}. Remove obsolete keys or regenerate the project template."
            ) from exc
        raise


def write_project_config(config: ProjectConfig, path: Path) -> None:
    path.write_text(yaml.safe_dump(config.model_dump(), sort_keys=False), encoding="utf-8")
