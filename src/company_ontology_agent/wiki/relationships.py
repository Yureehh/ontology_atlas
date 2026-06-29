from __future__ import annotations

from collections import defaultdict

from company_ontology_agent.graph.models import Assertion, Entity, EntityType, ExtractedGraph

RelationshipItem = tuple[Assertion, Entity, Entity]

SECTION_RULES: list[tuple[str, set[str], set[str]]] = [
    (
        "Architecture Relationships",
        {"depends_on", "uses", "runs_on", "deploys_to", "part_of", "supports"},
        {"Module", "System", "DeploymentUnit", "Technology", "ExternalService"},
    ),
    (
        "API Relationships",
        {"exposes", "handles", "calls", "requires"},
        {"APIEndpoint", "Function", "Module", "System"},
    ),
    (
        "Data Relationships",
        {
            "reads_from",
            "writes_to",
            "stores",
            "generates",
            "team_in_league",
            "match_in_league",
            "team_played_match",
            "player_played_match",
            "player_played_for",
        },
        {"DataModel", "Database", "DataStore", "BusinessEntity"},
    ),
    (
        "Model/Prediction Relationships",
        {
            "predicts",
            "evaluates",
            "model_artifact_describes",
            "model_artifact_generated",
            "prediction_for_match",
        },
        {"BusinessEntity", "DataModel", "Technology", "Class", "Function"},
    ),
    (
        "Market/Bet Relationships",
        {"prediction_uses_market", "bet_on_match", "bet_uses_market"},
        {"BusinessEntity"},
    ),
    (
        "Supporting Code Relationships",
        {"defines", "calls", "imports", "imports_from", "inherits", "references", "contains"},
        {"File", "Class", "Function", "Concept"},
    ),
]

PREDICATE_WEIGHTS = {
    "exposes": 12,
    "depends_on": 11,
    "reads_from": 10,
    "writes_to": 10,
    "generates": 10,
    "predicts": 10,
    "evaluates": 10,
    "model_artifact_generated": 12,
    "model_artifact_describes": 11,
    "prediction_uses_market": 10,
    "prediction_for_match": 9,
    "uses": 8,
    "calls": 7,
    "defines": 5,
    "contains": 1,
    "references": 1,
}

TYPE_WEIGHTS = {
    EntityType.api_endpoint: 10,
    EntityType.module: 9,
    EntityType.system: 9,
    EntityType.data_model: 8,
    EntityType.database: 8,
    EntityType.data_store: 8,
    EntityType.deployment_unit: 7,
    EntityType.business_entity: 7,
    EntityType.technology: 6,
    EntityType.external_service: 6,
    EntityType.class_: 4,
    EntityType.function: 3,
    EntityType.file: 1,
    EntityType.concept: 1,
}


def key_relationship_sections(
    graph: ExtractedGraph,
    *,
    per_section: int = 12,
) -> dict[str, list[RelationshipItem]]:
    entities_by_id = {entity.id: entity for entity in graph.entities}
    items = [
        (assertion, entities_by_id[assertion.subject_id], entities_by_id[assertion.object_id])
        for assertion in graph.assertions
        if assertion.subject_id in entities_by_id and assertion.object_id in entities_by_id
    ]
    degree = _degree(items)
    sections: dict[str, list[RelationshipItem]] = {}
    used: set[str] = set()
    for name, predicates, types in SECTION_RULES:
        candidates = [
            item
            for item in items
            if item[0].id not in used and _belongs_to_section(item, predicates, types)
        ]
        selected = _select_diverse(candidates, degree, per_section)
        sections[name] = selected
        used.update(assertion.id for assertion, _, _ in selected)
    return sections


def key_relationship_ids(graph: ExtractedGraph) -> set[str]:
    ids: set[str] = set()
    for items in key_relationship_sections(graph).values():
        ids.update(assertion.id for assertion, _, _ in items)
    return ids


def _belongs_to_section(
    item: RelationshipItem, predicates: set[str], mapped_or_entity_types: set[str]
) -> bool:
    assertion, subject, object_ = item
    if assertion.predicate in predicates:
        return True
    if assertion.predicate == "contains":
        return False
    mapped_types = {
        str(subject.metadata.get("mapped_type", subject.type.value)),
        str(object_.metadata.get("mapped_type", object_.type.value)),
        subject.type.value,
        object_.type.value,
    }
    if "BusinessEntity" in mapped_or_entity_types:
        return False
    return bool(mapped_types & mapped_or_entity_types)


def _select_diverse(
    items: list[RelationshipItem],
    degree: dict[str, int],
    limit: int,
) -> list[RelationshipItem]:
    selected: list[RelationshipItem] = []
    source_counts: dict[str, int] = defaultdict(int)
    low_value_contains_counts: dict[str, int] = defaultdict(int)
    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    predicate_counts: dict[str, int] = defaultdict(int)
    for item in sorted(items, key=lambda candidate: _score(candidate, degree), reverse=True):
        assertion, subject, object_ = item
        source_key = assertion.source_path or subject.source_path or "synthetic"
        type_pair = (subject.type.value, object_.type.value)
        if assertion.predicate == "contains" and subject.type == EntityType.file:
            if low_value_contains_counts[source_key] >= 1:
                continue
        if source_counts[source_key] >= 3:
            continue
        if pair_counts[type_pair] >= 4:
            continue
        if predicate_counts[assertion.predicate] >= 4:
            continue
        selected.append(item)
        source_counts[source_key] += 1
        if assertion.predicate == "contains" and subject.type == EntityType.file:
            low_value_contains_counts[source_key] += 1
        pair_counts[type_pair] += 1
        predicate_counts[assertion.predicate] += 1
        if len(selected) >= limit:
            break
    return selected


def _score(item: RelationshipItem, degree: dict[str, int]) -> float:
    assertion, subject, object_ = item
    predicate = PREDICATE_WEIGHTS.get(assertion.predicate, 4)
    types = TYPE_WEIGHTS.get(subject.type, 2) + TYPE_WEIGHTS.get(object_.type, 2)
    evidence = 1 if assertion.evidence_text or assertion.evidence_span_id else 0
    centrality = min(8, degree.get(subject.id, 0) + degree.get(object_.id, 0)) * 0.4
    low_value_penalty = (
        6 if assertion.predicate == "contains" and subject.type == EntityType.file else 0
    )
    return predicate + types + evidence + assertion.confidence * 2 + centrality - low_value_penalty


def _degree(items: list[RelationshipItem]) -> dict[str, int]:
    degree: dict[str, int] = defaultdict(int)
    for _, subject, object_ in items:
        degree[subject.id] += 1
        degree[object_.id] += 1
    return degree
