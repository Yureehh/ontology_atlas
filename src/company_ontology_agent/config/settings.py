from __future__ import annotations

import os
from dataclasses import dataclass

from company_ontology_agent.config.project_config import ProjectConfig


@dataclass(frozen=True)
class RuntimeSettings:
    neo4j_uri: str
    neo4j_database: str
    neo4j_user: str | None
    neo4j_password: str | None
    llm_api_key: str | None
    llm_model: str | None


def runtime_settings(config: ProjectConfig) -> RuntimeSettings:
    return RuntimeSettings(
        neo4j_uri=os.getenv(config.graph.uri_env, config.graph.uri),
        neo4j_database=os.getenv(config.graph.database_env, config.graph.database),
        neo4j_user=os.getenv(config.graph.username_env),
        neo4j_password=os.getenv(config.graph.password_env),
        llm_api_key=os.getenv(config.llm.api_key_env),
        llm_model=os.getenv(config.llm.model_env),
    )
