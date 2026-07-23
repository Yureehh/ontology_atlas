"""Server-side ranking and pruning shared by the portal and the wiki.

The full graph (every entity/assertion) is always written to ``graph.json`` and
Neo4j. The *portal pages*, however, only inline a bounded, pre-ranked subset so the
HTML stays small enough to open offline. The wiki uses the same ranking to decide
which structured-data entities deserve their own page, which guarantees that every
node the portal renders has a wiki page to link to.

Ranking reuses the wiki's relationship/type weights so importance is defined once.
"""

from __future__ import annotations

from collections import defaultdict

from company_ontology_agent.graph.models import Entity, ExtractedGraph, entity_graph_kind
from company_ontology_agent.utils.ids import stable_id
from company_ontology_agent.wiki.relationships import (
    PREDICATE_WEIGHTS,
    TYPE_WEIGHTS,
    key_relationship_sections,
)

# Per-page inline limits. The repo layer is small (~1.4k nodes) so it can show most
# of its structure; the data layer is dominated by per-row nodes, so it is capped
# both globally and per type to stay representative — hundreds of near-identical row
# dots read as noise. "Load full graph" still pulls everything on demand.
DATA_LIMIT = 300
DATA_PER_TYPE_CAP = 60
ARCHITECTURE_LIMIT = 30

# How many structured entities per mapped type get their own wiki page. Kept >= the
# portal's per-type cap so any node the portal can render also has a page.
WIKI_PER_TYPE_CAP = 250

_DEFAULT_PREDICATE_WEIGHT = 4
_TYPE_PRIORITY: dict[str, int] = {
    entity_type.value: weight for entity_type, weight in TYPE_WEIGHTS.items()
}

Node = dict[str, object]
Link = dict[str, object]


def aggregate_explore(
    nodes: list[Node],
    links: list[Link],
    *,
    architecture_limit: int = ARCHITECTURE_LIMIT,
) -> tuple[list[Node], list[Link]]:
    """Aggregate architecture while plotting a bounded set of real business entities."""
    data_nodes = [
        node
        for node in nodes
        if node.get("graph_kind") == "data" and not node.get("semantic_summary")
    ]
    data_ids = {str(node["id"]) for node in data_nodes}
    data_links = [
        link
        for link in links
        if str(link.get("source")) in data_ids and str(link.get("target")) in data_ids
    ]
    shown_data_nodes, shown_data_links = prune_layer(
        data_nodes,
        data_links,
        limit=DATA_LIMIT,
        per_type_cap=DATA_PER_TYPE_CAP,
        link_limit=1_800,
    )

    groups: dict[tuple[str, str], list[Node]] = defaultdict(list)
    original_group: dict[str, tuple[str, str]] = {}
    for node in nodes:
        graph_kind = str(node.get("graph_kind") or "repo")
        if graph_kind == "data":
            continue
        if not _architecture_visible(node):
            continue
        label = architecture_group(node)
        key = (graph_kind, label)
        groups[key].append(node)
        original_group[str(node["id"])] = key

    repo_groups = sorted(
        (key for key in groups if key[0] == "repo"),
        key=lambda key: (-len(groups[key]), key[1]),
    )
    if len(repo_groups) > architecture_limit:
        keep = set(repo_groups[: max(1, architecture_limit - 1)])
        other = ("repo", "Other architecture")
        for key in repo_groups:
            if key in keep:
                continue
            for node in groups.pop(key):
                groups[other].append(node)
                original_group[str(node["id"])] = other

    aggregate_nodes: list[Node] = []
    aggregate_id: dict[tuple[str, str], str] = {}
    for key, members in sorted(groups.items()):
        graph_kind, label = key
        identifier = stable_id("portal_group", graph_kind, label)
        aggregate_id[key] = identifier
        datasets = sorted({str(member.get("dataset") or "") for member in members} - {""})
        domains = sorted({str(member.get("domain") or "") for member in members} - {""})
        sources = sorted({str(member.get("source_path") or "") for member in members} - {""})
        connectors = sorted({str(member.get("connector") or "") for member in members} - {""})
        mapped_types = sorted({_display_type(member) for member in members} - {""})
        display_type = "ArchitectureGroup"
        short_label = _short_architecture_label(label)
        component_types = ", ".join(mapped_types[:3]) or "repository components"
        aggregate_nodes.append(
            {
                "id": identifier,
                "name": short_label,
                "full_name": label,
                "type": display_type,
                "mapped_type": display_type,
                "visual_type": display_type,
                "community": short_label,
                "group_key": label,
                "aggregate_kind": "architecture",
                "domain": ", ".join(domains),
                "dataset": ", ".join(datasets),
                "connector": ", ".join(connectors),
                "source_path": sources[0] if len(sources) == 1 else None,
                "source_paths": sources[:12],
                "authority": "Authoritative" if graph_kind == "data" else "Evidence-backed",
                "description": f"{len(members):,} {component_types}",
                "graph_kind": graph_kind,
                "extraction_source": "portal_aggregate",
                "confidence_tier": "summary",
                "member_count": len(members),
                "wiki": None,
            }
        )

    link_groups: dict[tuple[str, str, str], list[Link]] = defaultdict(list)
    for link in links:
        source_key = original_group.get(str(link.get("source")))
        target_key = original_group.get(str(link.get("target")))
        if source_key is None or target_key is None or source_key == target_key:
            continue
        source = aggregate_id[source_key]
        target = aggregate_id[target_key]
        predicate = str(link.get("predicate") or "related_to")
        link_groups[(source, target, predicate)].append(link)

    aggregate_links: list[Link] = []
    for (source, target, predicate), members in sorted(
        link_groups.items(), key=lambda item: (-len(item[1]), item[0])
    )[:240]:
        aggregate_links.append(
            {
                "id": stable_id("portal_group_link", source, predicate, target),
                "source": source,
                "target": target,
                "predicate": predicate,
                "confidence": max(_number(member.get("confidence")) for member in members),
                "evidence": f"{len(members):,} underlying relationship(s)",
                "graph_kind": "data"
                if any(
                    node["id"] in {source, target} and node["graph_kind"] == "data"
                    for node in aggregate_nodes
                )
                else "repo",
                "dataset": "",
                "extraction_source": "portal_aggregate",
                "confidence_tier": "summary",
                "evidence_level": "summary",
                "key_relationship": any(bool(member.get("key_relationship")) for member in members),
                "member_count": len(members),
            }
        )
    return aggregate_nodes + shown_data_nodes, aggregate_links + shown_data_links


def architecture_group(node: Node) -> str:
    path = str(node.get("source_path") or "").strip("/")
    if path:
        parts = [part for part in path.split("/") if part and not part.startswith(".")]
        for marker in ("packages", "services", "apps", "src"):
            if marker in parts:
                index = parts.index(marker)
                if index + 1 < len(parts):
                    return f"{marker}/{parts[index + 1]}"
        ignored = {"data", "raw", "lib", "app"}
        parts = [part for part in parts if part not in ignored]
        if len(parts) > 1 and "." not in parts[1]:
            return "/".join(parts[:2])
        if parts:
            return parts[0].rsplit(".", 1)[0]
    community = str(node.get("community") or "").strip()
    if community:
        return community
    return _display_type(node) or "Architecture"


def _architecture_visible(node: Node) -> bool:
    path = str(node.get("source_path") or "").casefold().replace("\\", "/")
    parts = {part for part in path.split("/") if part}
    hidden_parts = {
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "generated",
        "logs",
        "node_modules",
        "site-packages",
        "tests",
    }
    if parts & hidden_parts or any(part.startswith("test_") for part in parts):
        return False
    entity_type = str(node.get("type") or "").casefold()
    return bool(path) or entity_type not in {"class", "function", "method"}


def _short_architecture_label(value: str) -> str:
    label = value.strip().replace("_", " ")
    parts = [part for part in label.split("/") if part]
    if len(parts) > 1 and parts[0].lower() in {"packages", "services", "apps", "src"}:
        label = parts[-1]
    label = label.rsplit(".", 1)[0] if "." in label and " " not in label else label
    words = label.split()
    if len(words) > 4:
        label = " ".join(words[:4])
    return label[:28].strip().title() or "Architecture"


def _display_type(node: Node) -> str:
    return str(node.get("visual_type") or node.get("mapped_type") or node.get("type") or "")


def _number(value: object) -> float:
    return float(value) if isinstance(value, (int, float, str)) else 0.0


def _weighted_degree(nodes: list[Node], links: list[Link]) -> dict[str, float]:
    score: dict[str, float] = {str(node["id"]): 0.0 for node in nodes}
    for link in links:
        weight = PREDICATE_WEIGHTS.get(str(link.get("predicate")), _DEFAULT_PREDICATE_WEIGHT)
        source, target = str(link.get("source")), str(link.get("target"))
        if source in score:
            score[source] += weight
        if target in score:
            score[target] += weight
    return score


def prune_layer(
    nodes: list[Node],
    links: list[Link],
    *,
    limit: int,
    per_type_cap: int | None = None,
    link_limit: int | None = None,
) -> tuple[list[Node], list[Link]]:
    """Return the top-``limit`` nodes (by weighted degree + type priority) and their links.

    When ``per_type_cap`` is set, each mapped type is capped before the global cut so a
    high-cardinality type cannot crowd out the rest of the graph.
    """
    weighted = _weighted_degree(nodes, links)

    def score(node: Node) -> float:
        authority = 3 if str(node.get("authority") or "").lower() == "authoritative" else 0
        summary = 2 if node.get("semantic_summary") else 0
        return (
            weighted.get(str(node["id"]), 0.0)
            + _TYPE_PRIORITY.get(_display_type(node), 0)
            + authority
            + summary
        )

    candidates = nodes
    if per_type_cap:
        grouped: dict[str, list[Node]] = defaultdict(list)
        for node in nodes:
            grouped[_display_type(node)].append(node)
        candidates = []
        for group in grouped.values():
            group.sort(key=lambda node: (-score(node), str(node.get("name", ""))))
            candidates.extend(group[:per_type_cap])

    ranked = sorted(candidates, key=lambda node: (-score(node), str(node.get("name", ""))))[:limit]
    kept_ids = {str(node["id"]) for node in ranked}
    kept_links = [
        link
        for link in links
        if str(link["source"]) in kept_ids and str(link["target"]) in kept_ids
    ]
    if link_limit and len(kept_links) > link_limit:
        # Too many edges melts SVG; keep the highest-weighted (key relationships rank top).
        kept_links.sort(
            key=lambda link: PREDICATE_WEIGHTS.get(
                str(link.get("predicate")), _DEFAULT_PREDICATE_WEIGHT
            ),
            reverse=True,
        )
        kept_links = kept_links[:link_limit]
    return ranked, kept_links


def key_relationship_endpoint_ids(graph: ExtractedGraph) -> frozenset[str]:
    """Entity ids touched by the wiki's curated key relationships."""
    ids: set[str] = set()
    for items in key_relationship_sections(graph).values():
        for _assertion, subject, object_ in items:
            ids.add(subject.id)
            ids.add(object_.id)
    return frozenset(ids)


def page_worthy_entity_ids(graph: ExtractedGraph) -> set[str]:
    """Ids of entities that should get a wiki page.

    Keeps every repo/code entity (tractable and considered good), plus the top
    structured entities per mapped type and the endpoints of curated key
    relationships. This collapses the per-row structured explosion without dropping
    anything the portal can surface.
    """
    weighted: dict[str, float] = defaultdict(float)
    for assertion in graph.assertions:
        weight = PREDICATE_WEIGHTS.get(assertion.predicate, _DEFAULT_PREDICATE_WEIGHT)
        weighted[assertion.subject_id] += weight
        weighted[assertion.object_id] += weight

    ids: set[str] = set()
    structured: dict[str, list[Entity]] = defaultdict(list)
    for entity in graph.entities:
        if entity_graph_kind(entity) == "repo":
            ids.add(entity.id)
        else:
            mapped_type = str(entity.metadata.get("mapped_type") or entity.type.value)
            structured[mapped_type].append(entity)

    for entities in structured.values():
        entities.sort(key=lambda entity: (-weighted.get(entity.id, 0.0), entity.name))
        ids.update(entity.id for entity in entities[:WIKI_PER_TYPE_CAP])

    ids.update(key_relationship_endpoint_ids(graph))
    return ids
