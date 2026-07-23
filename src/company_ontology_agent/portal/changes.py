"""Shape run-to-run changes into decision-level groups instead of record dumps."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from company_ontology_agent.graph.diffing import GraphDiff
from company_ontology_agent.graph.models import Assertion, Entity, EntityType
from company_ontology_agent.utils.display import is_opaque_entity_name, public_entity_type

_REPRESENTATIVE_CAP = 5


def baseline_compatibility(project_root: Path, *, has_baseline: bool) -> tuple[bool, str | None]:
    if not has_baseline:
        return True, None
    current = project_root / "data" / "processed" / "scope-fingerprint.json"
    previous = project_root / "data" / "processed" / "scope-fingerprint.prev.json"
    unconfigured = not (project_root / "project.yaml").exists()
    if not current.exists() and not previous.exists() and unconfigured:
        return True, None  # lightweight library/test usage without a configured project
    if not current.exists() or not previous.exists():
        return False, "This baseline predates ingestion fingerprints and cannot be compared safely."
    try:
        current_digest = json.loads(current.read_text(encoding="utf-8")).get("digest")
        previous_digest = json.loads(previous.read_text(encoding="utf-8")).get("digest")
    except (json.JSONDecodeError, OSError):
        return False, "The comparison fingerprint is unreadable. Rebuild a clean baseline."
    if not current_digest or current_digest != previous_digest:
        return (
            False,
            "Source scope, mappings, row limits, or extraction settings changed. "
            "A mass diff would be misleading, so this comparison was intentionally stopped.",
        )
    return True, None


def _entity_group(entity: Entity) -> tuple[str, str]:
    dataset = str(entity.metadata.get("dataset") or "")
    mapped_type = str(entity.metadata.get("mapped_type") or "")
    if dataset:
        return "Business data", f"{dataset} · {mapped_type or public_entity_type(entity)}"
    area = entity.community or _source_area(entity.source_path) or public_entity_type(entity)
    return "Architecture", area


def _source_area(source_path: str | None) -> str:
    if not source_path:
        return ""
    parts = [part for part in source_path.replace("\\", "/").split("/") if part not in {".", ".."}]
    return parts[0] if parts else ""


def _group_entities(entities: list[Entity]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Entity]] = defaultdict(list)
    for entity in entities:
        grouped[_entity_group(entity)].append(entity)
    return [
        {
            "category": category,
            "label": label,
            "count": len(members),
            "representatives": [
                member.name
                for member in members
                if member.type is not EntityType.business_entity
                or bool(member.metadata.get("semantic_summary"))
                if not is_opaque_entity_name(member.name)
            ][:_REPRESENTATIVE_CAP],
        }
        for (category, label), members in sorted(
            grouped.items(), key=lambda item: (-len(item[1]), item[0])
        )
    ]


def _is_business_data(entity: Entity | None) -> bool:
    return bool(
        entity
        and (
            entity.type is EntityType.business_entity
            or entity.extraction_source == "structured_connector"
            or entity.metadata.get("connector")
        )
    )


def _relationship_counts(
    assertions: list[Assertion], entity_by_id: dict[str, Entity]
) -> tuple[int, int]:
    business = sum(
        _is_business_data(entity_by_id.get(assertion.subject_id))
        or _is_business_data(entity_by_id.get(assertion.object_id))
        for assertion in assertions
    )
    return len(assertions) - business, business


def _affected_components(
    changed_ids: set[str],
    assertions: list[Assertion],
    entity_by_id: dict[str, Entity],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for assertion in assertions:
        subject_changed = assertion.subject_id in changed_ids
        object_changed = assertion.object_id in changed_ids
        if subject_changed == object_changed:
            continue
        neighbor_id = assertion.object_id if subject_changed else assertion.subject_id
        neighbor = entity_by_id.get(neighbor_id)
        if neighbor is None:
            continue
        if neighbor.type is EntityType.function:
            continue
        if neighbor.type is EntityType.concept and len(neighbor.name) > 60:
            continue
        direction = "downstream" if subject_changed else "upstream"
        if _is_business_data(neighbor):
            area = str(neighbor.metadata.get("dataset") or "Structured data")
            entity_type = str(neighbor.metadata.get("mapped_type") or public_entity_type(neighbor))
            name = f"{area} · {entity_type}"
        else:
            area = neighbor.community or _source_area(neighbor.source_path) or "Architecture"
            entity_type = public_entity_type(neighbor)
            name = neighbor.name
        key = (direction, name, entity_type, area)
        row = grouped.setdefault(
            key,
            {
                "direction": direction,
                "name": name,
                "type": entity_type,
                "area": area,
                "relationship_count": 0,
                "predicates": set(),
            },
        )
        row["relationship_count"] += 1
        row["predicates"].add(assertion.predicate)
    return [
        {**row, "predicates": sorted(row["predicates"])[:5]}
        for row in sorted(
            grouped.values(),
            key=lambda item: (-item["relationship_count"], item["direction"], item["name"]),
        )[:24]
    ]


def _group_assertions(
    assertions: list[Assertion], entity_by_id: dict[str, Entity]
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], int] = defaultdict(int)
    for assertion in assertions:
        source = entity_by_id.get(assertion.subject_id)
        target = entity_by_id.get(assertion.object_id)
        source_label = _entity_group(source)[1] if source else "Removed entity"
        target_label = _entity_group(target)[1] if target else "Removed entity"
        grouped[(assertion.predicate, source_label, target_label)] += 1
    return [
        {"predicate": predicate, "source": source, "target": target, "count": count}
        for (predicate, source, target), count in sorted(
            grouped.items(), key=lambda item: (-item[1], item[0])
        )
    ]


def shape_changes(
    diff: GraphDiff,
    current_entities: list[Entity],
    previous_entities: list[Entity],
    current_assertions: list[Assertion] | None = None,
    previous_assertions: list[Assertion] | None = None,
    *,
    compatible: bool = True,
    incompatibility_reason: str | None = None,
) -> dict[str, Any]:
    if not diff.has_baseline:
        return {"has_baseline": False, "compatible": True}
    if not compatible:
        return {
            "has_baseline": True,
            "compatible": False,
            "incompatibility_reason": incompatibility_reason,
        }

    entity_by_id = {entity.id: entity for entity in previous_entities}
    entity_by_id.update({entity.id: entity for entity in current_entities})
    current_assertions = current_assertions or []
    previous_assertions = previous_assertions or []
    meaningful_modifications = [
        change for change in diff.entities_modified if set(change.fields) - {"community"}
    ]
    architecture_added = sum(not _is_business_data(entity) for entity in diff.entities_added)
    architecture_removed = sum(not _is_business_data(entity) for entity in diff.entities_removed)
    architecture_relationships_added, business_relationships_added = _relationship_counts(
        diff.assertions_added, entity_by_id
    )
    architecture_relationships_removed, business_relationships_removed = _relationship_counts(
        diff.assertions_removed, entity_by_id
    )
    changed_ids = {
        *(entity.id for entity in diff.entities_added),
        *(entity.id for entity in diff.entities_removed),
        *(change.id for change in meaningful_modifications),
    }
    adjacent_assertions = {
        assertion.id: assertion for assertion in [*previous_assertions, *current_assertions]
    }
    return {
        "has_baseline": True,
        "compatible": True,
        "summary": {
            "entities_added": len(diff.entities_added),
            "entities_removed": len(diff.entities_removed),
            "entities_modified": len(meaningful_modifications),
            "relationships_added": len(diff.assertions_added),
            "relationships_removed": len(diff.assertions_removed),
            "architecture_entities_added": architecture_added,
            "architecture_entities_removed": architecture_removed,
            "business_records_added": len(diff.entities_added) - architecture_added,
            "business_records_removed": len(diff.entities_removed) - architecture_removed,
            "architecture_relationships_added": architecture_relationships_added,
            "architecture_relationships_removed": architecture_relationships_removed,
            "business_relationships_added": business_relationships_added,
            "business_relationships_removed": business_relationships_removed,
        },
        "entity_groups_added": _group_entities(diff.entities_added),
        "entity_groups_removed": _group_entities(diff.entities_removed),
        "relationship_groups_added": _group_assertions(diff.assertions_added, entity_by_id),
        "relationship_groups_removed": _group_assertions(diff.assertions_removed, entity_by_id),
        "modified_components": [
            {
                "name": change.name,
                "type": change.type,
                "fields": sorted(change.fields),
            }
            for change in meaningful_modifications[:25]
            if change.type != EntityType.business_entity.value
        ],
        "affected_components": _affected_components(
            changed_ids,
            list(adjacent_assertions.values()),
            entity_by_id,
        ),
    }
