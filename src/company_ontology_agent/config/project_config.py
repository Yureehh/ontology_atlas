from __future__ import annotations

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
    no_viz: bool = False
    export_neo4j_cypher: bool = True
    push_to_neo4j: bool = False
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


class PrivacyConfig(BaseModel):
    pii_mode: str = "basic_redaction"
    classification_default: str = "internal"


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
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    ontology: OntologyConfig = Field(default_factory=OntologyConfig)
    wiki: WikiConfig = Field(default_factory=WikiConfig)
    sources: list[SourceConfig] = Field(default_factory=lambda: [SourceConfig(name="local_docs")])
    datasets: list[DatasetConfig] = Field(default_factory=list)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
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


def load_project_config(root: Path | None = None) -> ProjectConfig:
    project_root = root or find_project_root()
    with (project_root / "project.yaml").open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return ProjectConfig.model_validate(data)


def write_project_config(config: ProjectConfig, path: Path) -> None:
    path.write_text(yaml.safe_dump(config.model_dump(), sort_keys=False), encoding="utf-8")
