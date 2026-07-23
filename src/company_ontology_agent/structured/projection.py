from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from company_ontology_agent.config.project_config import DatasetConfig, ProjectConfig
from company_ontology_agent.graph.models import (
    Assertion,
    Chunk,
    Entity,
    EntityType,
    ExtractedGraph,
    Source,
    SourceSpan,
)
from company_ontology_agent.ontology.mappings import normalize_predicate
from company_ontology_agent.structured.connectors import load_dataset
from company_ontology_agent.structured.mapping import load_dataset_mapping
from company_ontology_agent.structured.models import DatasetInspection, DatasetMapping
from company_ontology_agent.utils.hashing import stable_hash
from company_ontology_agent.utils.ids import stable_id


def inspect_configured_datasets(
    project_root: Path, config: ProjectConfig
) -> list[DatasetInspection]:
    inspections = []
    for dataset_config in config.datasets:
        dataset = load_dataset(project_root, dataset_config)
        inspections.append(
            DatasetInspection(
                name=dataset.name,
                domain=dataset.domain,
                connector=dataset.connector,
                sources={
                    source: len(records)
                    for source, records in sorted(dataset.records_by_source.items())
                },
                columns={
                    source: sorted(records[0].values.keys()) if records else []
                    for source, records in sorted(dataset.records_by_source.items())
                },
            )
        )
    return inspections


def build_structured_graph(project_root: Path, config: ProjectConfig) -> ExtractedGraph:
    graph = ExtractedGraph(project_slug=config.project_slug)
    for dataset_config in config.datasets:
        if not dataset_config.enabled:
            continue
        dataset = load_dataset(project_root, dataset_config)
        mapping = load_dataset_mapping(project_root, dataset_config.mapping)
        graph = graph.merge(_project_dataset(config.project_slug, dataset_config, mapping, dataset))
    return graph


def _project_dataset(
    project_slug: str,
    dataset_config: DatasetConfig,
    mapping: DatasetMapping,
    dataset: Any,
) -> ExtractedGraph:
    now = datetime.now(UTC).isoformat()
    run_id = stable_id("run", project_slug, dataset_config.name, now)
    source = Source(
        id=stable_id("source", project_slug, dataset_config.name, dataset_config.connector),
        path=dataset_config.path or dataset_config.uri_env or dataset_config.name,
        source_type=f"structured:{dataset_config.connector}",
        sha256=stable_hash(_dataset_fingerprint(dataset.records_by_source)),
        title=dataset_config.name,
    )
    span = SourceSpan(
        id=stable_id("span", source.id, "dataset"),
        source_id=source.id,
        text=(
            f"Structured dataset {dataset_config.name} in domain "
            f"{dataset_config.domain} via {dataset_config.connector}."
        ),
    )
    chunk = Chunk(id=stable_id("chunk", span.id), source_span_id=span.id, text=span.text)

    entities_by_id: dict[str, Entity] = {}
    assertions_by_id: dict[str, Assertion] = {}
    by_alias_and_key: dict[tuple[str, str], Entity] = {}
    entity_ids_by_alias: dict[str, set[str]] = {}

    for alias, entity_mapping in mapping.entities.items():
        for record in dataset.records_by_source.get(entity_mapping.source, []):
            key_value = _mapping_key(record.values, entity_mapping.key)
            if not key_value:
                continue
            name = _mapping_name(record.values, entity_mapping.name) or key_value
            entity_id = stable_id("entity", dataset_config.domain, entity_mapping.type, key_value)
            entity = Entity(
                id=entity_id,
                type=EntityType.business_entity,
                name=name,
                normalized_name=name.lower(),
                source_span_ids=[span.id],
                source_path=f"{source.path}#{record.source}:{record.row_number}",
                extraction_source="structured_connector",
                confidence_tier="extracted",
                metadata={
                    "domain": dataset_config.domain,
                    "dataset": dataset_config.name,
                    "connector": dataset_config.connector,
                    "mapped_type": entity_mapping.type,
                    "source": entity_mapping.source,
                    "record_key": key_value,
                    "row_number": record.row_number,
                    "run_id": run_id,
                    "seen_at": now,
                    "queryable_properties": sorted(
                        set(entity_mapping.properties) - set(entity_mapping.redact)
                    ),
                    **_mapped_properties(
                        record.values,
                        entity_mapping.properties,
                        entity_mapping.redact,
                    ),
                },
            )
            entities_by_id.setdefault(entity.id, entity)
            by_alias_and_key[(alias, key_value)] = entities_by_id[entity.id]
            entity_ids_by_alias.setdefault(alias, set()).add(entity.id)

    for alias, entity_mapping in mapping.entities.items():
        member_ids = sorted(entity_ids_by_alias.get(alias, set()))
        if not member_ids:
            continue
        records = dataset.records_by_source.get(entity_mapping.source, [])
        fields = sorted({field for record in records for field in record.values})
        summary_id = stable_id(
            "dataset_summary", project_slug, dataset_config.name, alias, entity_mapping.type
        )
        summary = Entity(
            id=summary_id,
            type=EntityType.concept,
            name=f"{entity_mapping.type} in {dataset_config.name}",
            normalized_name=f"{entity_mapping.type} in {dataset_config.name}".lower(),
            source_span_ids=[span.id],
            source_path=source.path,
            extraction_source="structured_connector",
            confidence_tier="extracted",
            description=(
                f"Authoritative {entity_mapping.type} records from {dataset_config.name}."
            ),
            metadata={
                "domain": dataset_config.domain,
                "dataset": dataset_config.name,
                "connector": dataset_config.connector,
                "mapped_type": entity_mapping.type,
                "source": entity_mapping.source,
                "record_count": len(member_ids),
                "fields": fields,
                "authority": "authoritative",
                "semantic_summary": True,
                "run_id": run_id,
                "seen_at": now,
            },
        )
        entities_by_id[summary.id] = summary
        for member_id in member_ids:
            assertion_id = stable_id(
                "assertion", dataset_config.name, "member_of", member_id, summary.id
            )
            assertions_by_id[assertion_id] = Assertion(
                id=assertion_id,
                predicate="member_of",
                subject_id=member_id,
                object_id=summary.id,
                evidence_span_id=span.id,
                confidence=1.0,
                extractor="structured_connector",
                source_path=source.path,
                extraction_source="structured_connector",
                confidence_tier="extracted",
                evidence_text=(
                    f"{dataset_config.name} maps this record to {entity_mapping.type}."
                ),
                metadata={
                    "domain": dataset_config.domain,
                    "dataset": dataset_config.name,
                    "connector": dataset_config.connector,
                    "mapped_type": entity_mapping.type,
                    "authority": "authoritative",
                    "run_id": run_id,
                    "seen_at": now,
                },
            )

    for relationship in mapping.relationships:
        from_mapping = mapping.entities[relationship.from_entity]
        for record in dataset.records_by_source.get(from_mapping.source, []):
            from_key = _mapping_key(record.values, from_mapping.key)
            to_key = _mapping_key(record.values, relationship.from_key)
            subject = by_alias_and_key.get((relationship.from_entity, from_key))
            object_ = by_alias_and_key.get((relationship.to_entity, to_key))
            if not subject or not object_:
                continue
            predicate = normalize_predicate(relationship.type)
            assertion_id = stable_id(
                "assertion",
                dataset_config.name,
                relationship.type,
                subject.id,
                object_.id,
            )
            assertions_by_id.setdefault(
                assertion_id,
                Assertion(
                    id=assertion_id,
                    predicate=predicate,
                    subject_id=subject.id,
                    object_id=object_.id,
                    evidence_span_id=span.id,
                    confidence=1.0,
                    extractor="structured_connector",
                    source_path=subject.source_path,
                    extraction_source="structured_connector",
                    confidence_tier="extracted",
                    evidence_text=(
                        f"{dataset_config.name}:{from_mapping.source} row "
                        f"{record.row_number} maps {relationship.type}."
                    ),
                    metadata={
                        "domain": dataset_config.domain,
                        "dataset": dataset_config.name,
                        "connector": dataset_config.connector,
                        "mapped_type": relationship.type,
                        "run_id": run_id,
                        "seen_at": now,
                    },
                ),
            )

    return ExtractedGraph(
        project_slug=project_slug,
        sources=[source],
        source_spans=[span],
        chunks=[chunk],
        entities=list(entities_by_id.values()),
        assertions=list(assertions_by_id.values()),
    )


def _dataset_fingerprint(records_by_source: dict[str, list[Any]]) -> str:
    parts = []
    for source, records in sorted(records_by_source.items()):
        parts.append(f"{source}:{len(records)}")
        for record in records:
            parts.append(str(sorted(record.values.items())))
    return "|".join(parts)


def _mapped_properties(
    values: dict[str, Any], properties: list[str], redacted: list[str]
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    redacted_set = set(redacted)
    for name in properties:
        if name not in values:
            continue
        output[name] = "[redacted]" if name in redacted_set else _native_scalar(values.get(name))
    return output


def _native_scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    isoformat = getattr(value, "isoformat", None)
    return str(isoformat()) if callable(isoformat) else str(value)


def _mapping_key(values: dict[str, Any], key: str | list[str]) -> str:
    if isinstance(key, str):
        return _string(values.get(key))
    parts = [_string(values.get(name)) for name in key]
    if any(not part for part in parts):
        return ""
    return "|".join(parts)


def _mapping_name(values: dict[str, Any], template: str) -> str:
    if "{" not in template:
        return _string(values.get(template))
    try:
        return template.format(**{key: _string(value) for key, value in values.items()})
    except KeyError:
        return ""


def _string(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
