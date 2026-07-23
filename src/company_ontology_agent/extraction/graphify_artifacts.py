from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from company_ontology_agent.graph.models import (
    Assertion,
    Entity,
    EntityType,
    ExtractedGraph,
    Source,
    SourceSpan,
)
from company_ontology_agent.ontology.mappings import normalize_predicate
from company_ontology_agent.utils.hashing import stable_hash
from company_ontology_agent.utils.ids import slugify, stable_id


def parse_graphify_graph(
    path: Path, project_slug: str, source_roots: Sequence[Path] = ()
) -> ExtractedGraph:
    raw_text = path.read_text(encoding="utf-8")
    data = json.loads(raw_text)
    raw_nodes = _extract_collection(data, "nodes")
    raw_edges = _extract_collection(data, "edges") or _extract_collection(data, "links")
    entities_by_raw_id: dict[str, Entity] = {}
    # Machine-independent label: absolute paths here would leak into stable IDs
    # and wiki page slugs, making outputs non-portable across machines.
    graphify_label = f"{path.parent.name}/{path.name}"
    graphify_source = Source(
        id=stable_id("source", "graphify", graphify_label),
        path=graphify_label,
        source_type="graphify_json",
        sha256=stable_hash(raw_text),
        title="Graphify graph.json",
    )

    spans: list[SourceSpan] = []
    for raw_node in raw_nodes:
        node = _as_dict(raw_node)
        raw_id = str(node.get("id") or node.get("key") or node.get("name") or node.get("label"))
        name = str(node.get("name") or node.get("label") or node.get("title") or raw_id)
        raw_type = node.get("type") or node.get("kind") or node.get("category")
        entity_type = _entity_type(str(raw_type or _graphify_node_type(node, name)))
        normalized = slugify(name).replace("-", " ")
        entities_by_raw_id[raw_id] = Entity(
            id=stable_id("entity", normalized, entity_type.value),
            type=entity_type,
            name=name,
            normalized_name=normalized,
            aliases=_string_list(node.get("aliases")),
            graphify_id=raw_id,
            source_path=_relative_source_path(
                _string_value(
                    node.get("path")
                    or node.get("file")
                    or node.get("filepath")
                    or node.get("source")
                    or node.get("source_file")
                ),
                source_roots,
            ),
            community=_string_value(
                node.get("community")
                or node.get("cluster")
                or node.get("group")
                or node.get("community_name")
            ),
            extraction_source=_graphify_extraction_source(node),
            confidence_tier="extracted",
            description=_string_value(
                node.get("description") or node.get("summary") or node.get("doc")
            ),
            metadata=_metadata(node),
        )

    assertions: list[Assertion] = []
    for index, raw_edge in enumerate(raw_edges):
        edge = _as_dict(raw_edge)
        source = entities_by_raw_id.get(
            str(edge.get("source") or edge.get("from") or edge.get("src") or "")
        )
        target = entities_by_raw_id.get(
            str(edge.get("target") or edge.get("to") or edge.get("dst") or "")
        )
        if source is None or target is None:
            continue
        predicate = normalize_predicate(
            slugify(
                str(
                    edge.get("predicate")
                    or edge.get("relationship")
                    or edge.get("relation")
                    or edge.get("type")
                    or edge.get("label")
                    or "related_to"
                )
            ).replace("-", "_")
        )
        source_path = _relative_source_path(
            _string_value(
                edge.get("path")
                or edge.get("file")
                or edge.get("filepath")
                or edge.get("source_path")
            ),
            source_roots,
        )
        evidence_id = stable_id("span", "graphify", path.name, index, source_path or "")
        evidence_text = str(
            edge.get("evidence")
            or edge.get("context")
            or edge.get("reason")
            or edge.get("label")
            or predicate
        )
        spans.append(
            SourceSpan(
                id=evidence_id,
                source_id=graphify_source.id,
                start=index,
                end=index,
                text=evidence_text,
            )
        )
        assertions.append(
            Assertion(
                id=stable_id("assertion", source.id, predicate, target.id, evidence_id),
                predicate=predicate,
                subject_id=source.id,
                object_id=target.id,
                evidence_span_id=evidence_id,
                confidence=_confidence(edge.get("confidence_score", edge.get("confidence"))),
                extractor="graphify",
                graphify_id=str(edge.get("id") or edge.get("key") or index),
                source_path=source_path,
                community=_string_value(edge.get("community") or edge.get("cluster")),
                extraction_source=_graphify_extraction_source(edge),
                confidence_tier=_confidence_tier(edge),
                evidence_text=evidence_text,
                metadata=_metadata(edge),
            )
        )

    return ExtractedGraph(
        project_slug=project_slug,
        sources=[graphify_source],
        source_spans=spans,
        entities=list(entities_by_raw_id.values()),
        assertions=assertions,
    )


def _extract_collection(data: Any, name: str) -> list[Any]:
    if isinstance(data, dict):
        value = data.get(name)
        if isinstance(value, list):
            return value
        graph = data.get("graph")
        if isinstance(graph, dict) and isinstance(graph.get(name), list):
            return cast(list[Any], graph[name])
    return []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _entity_type(value: str) -> EntityType:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    for entity_type in EntityType:
        if entity_type.value.lower() == normalized or entity_type.name.lower() == normalized:
            return entity_type
    return {
        "repo": EntityType.system,
        "repository": EntityType.system,
        "service": EntityType.system,
        "symbol": EntityType.function,
        "method": EntityType.function,
        "endpoint": EntityType.api_endpoint,
        "api": EntityType.api_endpoint,
        "model": EntityType.data_model,
        "table": EntityType.data_model,
        "db": EntityType.database,
        "database": EntityType.database,
        "datastore": EntityType.data_store,
        "store": EntityType.data_store,
        "queue": EntityType.queue,
        "external": EntityType.external_service,
        "external_service": EntityType.external_service,
        "deployment": EntityType.deployment_unit,
        "environment": EntityType.environment,
        "config": EntityType.config,
        "secret": EntityType.secret_ref,
        "workflow": EntityType.workflow,
        "role": EntityType.user_role,
    }.get(normalized, EntityType.concept)


def _graphify_node_type(node: dict[str, Any], name: str) -> str:
    file_type = str(node.get("file_type") or "").lower()
    origin = str(node.get("_origin") or node.get("origin") or "").lower()
    source_file = str(node.get("source_file") or node.get("file") or "")
    label = name.strip()
    label_lower = label.lower()
    if re.search(r"^(get|post|put|patch|delete)\s+/", label_lower):
        return "endpoint"
    if re.search(r"\b(get|post|put|patch|delete)\s*\(", label_lower) and "/" in label_lower:
        return "endpoint"
    file_suffixes = (".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".yaml", ".yml", ".toml", ".json")
    if label.endswith(file_suffixes) or ("/" in label and "." in Path(label).name):
        return "file"
    if label.endswith("()") or (
        origin == "ast" and re.search(r"[a-zA-Z_][\w_]*\(\)$", label)
    ):
        return "function"
    if file_type == "code" and source_file and label == Path(source_file).name:
        return "file"
    if file_type == "code" and label and label[:1].isupper() and " " not in label:
        return "class"
    return "concept"


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip() or None


def _relative_source_path(value: str | None, source_roots: Sequence[Path]) -> str | None:
    """Strip machine-specific prefixes so graph/wiki outputs are portable across machines."""
    if not value:
        return value
    path = Path(value)
    if not path.is_absolute():
        return value
    for root in source_roots:
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return value


def _graphify_extraction_source(value: dict[str, Any]) -> str:
    raw = str(
        value.get("extraction_source")
        or value.get("source")
        or value.get("origin")
        or value.get("_origin")
        or value.get("kind")
        or ""
    ).lower()
    if "semantic" in raw or "llm" in raw or "inferred" in raw:
        return "graphify_semantic"
    if "ast" in raw or "code" in raw or "symbol" in raw:
        return "graphify_ast"
    return "graphify"


def _metadata(value: dict[str, Any]) -> dict[str, str | int | float | bool | None]:
    return {
        str(key): item
        for key, item in value.items()
        if isinstance(item, str | int | float | bool) or item is None
    }


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return [value] if isinstance(value, str) and value else []


def _confidence(value: Any) -> float:
    return max(0.0, min(1.0, float(value))) if isinstance(value, int | float) else 0.7


def _confidence_tier(value: dict[str, Any]) -> str:
    raw = str(value.get("confidence") or value.get("confidence_tier") or "").strip().lower()
    if raw in {"extracted", "inferred", "ambiguous", "generated"}:
        return raw
    predicate = str(
        value.get("predicate")
        or value.get("relationship")
        or value.get("relation")
        or value.get("type")
        or value.get("label")
        or ""
    )
    return (
        "inferred"
        if normalize_predicate(predicate) in {"related_to", "supports"}
        else "extracted"
    )
