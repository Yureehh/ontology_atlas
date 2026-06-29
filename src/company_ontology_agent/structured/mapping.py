from __future__ import annotations

from pathlib import Path

import yaml

from company_ontology_agent.structured.models import DatasetMapping


def load_dataset_mapping(project_root: Path, path: str) -> DatasetMapping:
    mapping_path = Path(path)
    if not mapping_path.is_absolute():
        mapping_path = project_root / mapping_path
    payload = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) or {}
    mapping = DatasetMapping.model_validate(payload)
    validate_mapping(mapping)
    return mapping


def validate_mapping(mapping: DatasetMapping) -> None:
    for alias, entity in mapping.entities.items():
        if not entity.source:
            raise ValueError(f"Entity mapping {alias} is missing source")
        if not entity.key:
            raise ValueError(f"Entity mapping {alias} is missing key")
        if isinstance(entity.key, list) and any(not field for field in entity.key):
            raise ValueError(f"Entity mapping {alias} has an empty composite key field")
        if not entity.name:
            raise ValueError(f"Entity mapping {alias} is missing name")
    for relationship in mapping.relationships:
        if relationship.from_entity not in mapping.entities:
            raise ValueError(f"Unknown from_entity: {relationship.from_entity}")
        if relationship.to_entity not in mapping.entities:
            raise ValueError(f"Unknown to_entity: {relationship.to_entity}")
