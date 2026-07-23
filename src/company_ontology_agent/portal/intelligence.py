"""Build defensible, evidence-linked findings for the Insights page."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from company_ontology_agent.graph.models import (
    Entity,
    EntityType,
    ExtractedGraph,
    entity_graph_kind,
)
from company_ontology_agent.utils.display import public_entity_type
from company_ontology_agent.utils.source_paths import artifact_path

_GENERIC_NAMES = {
    "any",
    "dataframe",
    "dict",
    "index",
    "list",
    "none",
    "object",
    "optional",
    "path",
    "protocol",
    "series",
    "str",
    "string",
    "valueerror",
}
_ARCHITECTURE_FLOW_PREDICATES = {
    "calls",
    "depends_on",
    "imports",
    "imports_from",
    "inherits",
    "shares_data_with",
    "uses",
}
_HOTSPOT_TYPES = {
    EntityType.system,
    EntityType.package,
    EntityType.module,
    EntityType.class_,
    EntityType.data_model,
    EntityType.api_endpoint,
    EntityType.workflow,
    EntityType.data_store,
    EntityType.external_service,
}


def build_intelligence(
    graph: ExtractedGraph,
    *,
    report_exists: bool,
) -> dict[str, Any]:
    by_id = {entity.id: entity for entity in graph.entities}
    incoming: Counter[str] = Counter()
    outgoing: Counter[str] = Counter()
    degree: Counter[str] = Counter()
    for assertion in graph.assertions:
        outgoing[assertion.subject_id] += 1
        incoming[assertion.object_id] += 1
        degree[assertion.subject_id] += 1
        degree[assertion.object_id] += 1

    impact_hotspots = []
    for entity in sorted(
        (entity for entity in graph.entities if _is_actionable_architecture(entity)),
        key=lambda entity: (-degree[entity.id], entity.name),
    )[:12]:
        if degree[entity.id] == 0:
            continue
        impact_hotspots.append(
            {
                "id": entity.id,
                "name": entity.name,
                "type": public_entity_type(entity),
                "area": entity.community or _source_area(entity),
                "fan_in": incoming[entity.id],
                "fan_out": outgoing[entity.id],
                "degree": degree[entity.id],
                "source_path": entity.source_path,
            }
        )

    cross_boundaries = []
    lineage_groups: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    lineage_counts: Counter[tuple[str, str, str, str, str]] = Counter()
    for assertion in graph.assertions:
        source = by_id.get(assertion.subject_id)
        target = by_id.get(assertion.object_id)
        if source is None or target is None:
            continue
        source_kind = entity_graph_kind(source)
        target_kind = entity_graph_kind(target)
        source_area = source.community or _source_area(source)
        target_area = target.community or _source_area(target)
        row = {
            "source": source.name,
            "target": target.name,
            "predicate": assertion.predicate,
            "source_area": source_area,
            "target_area": target_area,
            "evidence": assertion.evidence_text,
            "source_path": assertion.source_path,
            "confidence": assertion.confidence,
        }
        if (
            source_kind == target_kind == "repo"
            and assertion.predicate in _ARCHITECTURE_FLOW_PREDICATES
            and source_area
            and target_area
            and source_area != target_area
            and _is_meaningful_entity(source)
            and _is_meaningful_entity(target)
        ):
            cross_boundaries.append(row)
        if (
            (source_kind != target_kind or _lineage_type(source) or _lineage_type(target))
            and _is_meaningful_entity(source)
            and _is_meaningful_entity(target)
        ):
            lineage_row = _lineage_row(source, target, assertion.predicate, row)
            key = (
                lineage_row["predicate"],
                lineage_row["source"],
                lineage_row["target"],
                lineage_row["source_type"],
                lineage_row["target_type"],
            )
            lineage_groups.setdefault(key, lineage_row)
            lineage_counts[key] += 1

    data_lineage = []
    for key, row in sorted(
        lineage_groups.items(), key=lambda item: (-lineage_counts[item[0]], item[0])
    ):
        count = lineage_counts[key]
        data_lineage.append(
            {
                **row,
                "count": count,
                "evidence": (
                    f"{count:,} graph relationship{'s' if count != 1 else ''} "
                    f"{'support' if count != 1 else 'supports'} this lineage."
                ),
            }
        )
    cross_boundaries = _aggregate_cross_boundaries(cross_boundaries)

    orphan_groups: Counter[tuple[str, str]] = Counter()
    for entity in graph.entities:
        if entity_graph_kind(entity) != "data" or degree[entity.id] != 0:
            continue
        orphan_groups[
            (
                str(entity.metadata.get("dataset") or "Structured data"),
                public_entity_type(entity),
            )
        ] += 1

    dataset_entities: dict[str, list[Entity]] = defaultdict(list)
    for entity in graph.entities:
        dataset = str(entity.metadata.get("dataset") or "")
        if dataset:
            dataset_entities[dataset].append(entity)
    ownership_gaps = [
        {"dataset": dataset, "records": len(items)}
        for dataset, items in sorted(dataset_entities.items())
        if not any(item.metadata.get("owner") for item in items)
    ]
    missing_evidence = sum(
        not (assertion.source_path or assertion.evidence_text or assertion.evidence_span_id)
        for assertion in graph.assertions
    )

    duplicate_names: dict[str, set[str]] = defaultdict(set)
    for entity in graph.entities:
        duplicate_names[entity.normalized_name].add(public_entity_type(entity))
    conflicts = [
        {"name": name, "types": sorted(types)}
        for name, types in duplicate_names.items()
        if name and len(types) > 1
    ][:20]

    return {
        "impact_hotspots": impact_hotspots,
        "cross_boundaries": cross_boundaries[:20],
        "data_lineage": data_lineage[:20],
        "orphan_groups": [
            {"dataset": dataset, "type": mapped_type, "count": count}
            for (dataset, mapped_type), count in orphan_groups.most_common(20)
        ],
        "ownership_gaps": ownership_gaps[:20],
        "evidence_gaps": {"relationships_without_evidence": missing_evidence},
        "conflicting_concepts": conflicts,
        "report_url": "../graphify-out/GRAPH_REPORT.md" if report_exists else None,
        "summary": {
            "hotspot_count": len(impact_hotspots),
            "cross_boundary_count": len(cross_boundaries),
            "lineage_count": len(data_lineage),
            "orphan_count": sum(orphan_groups.values()),
        },
    }
def _is_actionable_architecture(entity: Entity) -> bool:
    return (
        entity_graph_kind(entity) == "repo"
        and entity.type in _HOTSPOT_TYPES
        and _is_meaningful_entity(entity)
    )


def _is_meaningful_entity(entity: Entity) -> bool:
    if entity_graph_kind(entity) == "data":
        return True
    name = entity.name.strip()
    return (
        bool(name)
        and name.lower() not in _GENERIC_NAMES
        and not _is_test_entity(entity)
        and not name.lower().startswith(("oe:", "entity_"))
        and not (name.isupper() and "_" in name)
        and len(name) <= 80
        and len(name.split()) <= 8
        and not name.endswith(".")
    )


def _is_test_entity(entity: Entity) -> bool:
    text = f"{entity.name} {entity.source_path or ''}".lower()
    return "/test" in text or "tests/" in text or entity.name.startswith("test_")


def _source_area(entity: Entity) -> str:
    path = (entity.source_path or "").strip("/")
    if not path:
        return public_entity_type(entity)
    parts = [part for part in path.split("/") if part not in {"data", "raw"}]
    return "/".join(parts[:2]) if len(parts) > 1 else parts[0]


def _lineage_type(entity: Entity) -> bool:
    return bool(
        entity.metadata.get("semantic_summary")
        or entity.type
        in {
            EntityType.data_model,
            EntityType.database,
            EntityType.data_store,
            EntityType.system,
            EntityType.technology,
        }
    )


def _lineage_label(entity: Entity, graph_kind: str, public_type: str) -> str:
    if graph_kind == "repo" or entity.metadata.get("semantic_summary") is True:
        return entity.name
    return public_type


def _lineage_row(
    source: Entity,
    target: Entity,
    predicate: str,
    row: dict[str, Any],
) -> dict[str, Any]:
    source_kind = entity_graph_kind(source)
    target_kind = entity_graph_kind(target)
    source_type = public_entity_type(source)
    target_type = public_entity_type(target)
    source_name = _lineage_label(source, source_kind, source_type)
    target_name = _lineage_label(target, target_kind, target_type)
    return {
        **row,
        "source": source_name,
        "target": target_name,
        "source_type": source_type,
        "target_type": target_type,
        "source_area": row["source_area"] if source_kind == "repo" else source_type,
        "target_area": row["target_area"] if target_kind == "repo" else target_type,
        "source_path": artifact_path(str(row.get("source_path") or "")) or None,
        "predicate": predicate,
    }


def _aggregate_cross_boundaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str, str]] = Counter()
    for row in rows:
        counts[(row["source_area"], row["target_area"], row["predicate"])] += 1
    return [
        {
            "source": source_area,
            "target": target_area,
            "source_area": source_area,
            "target_area": target_area,
            "predicate": predicate,
            "count": count,
            "evidence": (
                f"{count:,} component relationship{'s' if count != 1 else ''} cross this boundary."
            ),
        }
        for (source_area, target_area, predicate), count in counts.most_common(20)
    ]
