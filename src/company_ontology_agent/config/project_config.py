from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class RuntimeConfig(BaseModel):
    backend: str = "local"
    metadata_store: str = "sqlite"
    raw_store: str = "local_filesystem"


class GraphConfig(BaseModel):
    backend: Literal["neo4j"] = "neo4j"
    uri: str = "bolt://localhost:7687"
    uri_env: str = "NEO4J_URI"
    database: str = "neo4j"
    database_env: str = "NEO4J_DATABASE"
    username_env: str = "NEO4J_USER"
    password_env: str = "NEO4J_PASSWORD"
    vector_index_name: str = "chunk_embeddings"
    write_visual_relationships: bool = True


class GraphifyConfig(BaseModel):
    enabled: bool = True
    input_path: str = "./data/raw"
    output_path: str = "./graphify-out"
    backend: str = "openai"
    mode: Literal["default", "deep"] = "deep"
    update: bool = True
    no_viz: bool = True
    strict: bool = False
    timeout_seconds: int | None = None
    auto_name_communities: bool = True


class LLMConfig(BaseModel):
    provider: str = "local"
    model_env: str = "ONTOLOGY_AGENT_LLM_MODEL"
    api_key_env: str = "OPENAI_API_KEY"
    extraction_mode: str = "strict_json_schema"


class EmbeddingConfig(BaseModel):
    provider: str = "none"
    model_env: str = "ONTOLOGY_AGENT_EMBEDDING_MODEL"
    dimension: int = 1536


class RagConfig(BaseModel):
    enabled: bool = False
    top_k: int = Field(default=8, ge=1, le=50)
    max_hops: int = Field(default=2, ge=1, le=3)


class ExtractionConfig(BaseModel):
    ontology_projection_enabled: bool = False
    local_fallback_enabled: bool = False


class OntologyConfig(BaseModel):
    version: str = "0.1.0"
    core_path: str = "./ontology/core.ttl"
    shapes_path: str = "./ontology/shapes.ttl"
    mappings_path: str = "./ontology/mappings.yaml"
    validation_mode: Literal["strict", "warn"] = "strict"


class WikiConfig(BaseModel):
    enabled: bool = True
    output_path: str = "./wiki"
    format: Literal["markdown"] = "markdown"
    include_frontmatter: bool = True


class SourceConfig(BaseModel):
    name: str
    type: str = "folder"
    path: str = "./data/raw"
    enabled: bool = True


class DatasetConfig(BaseModel):
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


class SyncConfig(BaseModel):
    incremental: bool = True
    idempotency: bool = True


class ProjectConfig(BaseModel):
    project_slug: str
    project_name: str
    environment: str = "local"
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    graph: GraphConfig = Field(default_factory=GraphConfig)
    graphify: GraphifyConfig = Field(default_factory=GraphifyConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    rag: RagConfig = Field(default_factory=RagConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    ontology: OntologyConfig = Field(default_factory=OntologyConfig)
    wiki: WikiConfig = Field(default_factory=WikiConfig)
    sources: list[SourceConfig] = Field(default_factory=lambda: [SourceConfig(name="local_docs")])
    datasets: list[DatasetConfig] = Field(default_factory=list)
    sync: SyncConfig = Field(default_factory=SyncConfig)


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
    return ProjectConfig.model_validate(data)


def write_project_config(config: ProjectConfig, path: Path) -> None:
    path.write_text(yaml.safe_dump(config.model_dump(), sort_keys=False), encoding="utf-8")
