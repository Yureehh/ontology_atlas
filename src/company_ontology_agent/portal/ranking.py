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
from company_ontology_agent.wiki.relationships import (
    PREDICATE_WEIGHTS,
    TYPE_WEIGHTS,
    key_relationship_sections,
)

# Per-page inline limits. The repo layer is small (~1.4k nodes) so it can show most
# of its structure; the data layer is dominated by per-row nodes, so it is capped
# both globally and per type to stay representative rather than 300 near-identical rows.
REPO_LIMIT = 500
DATA_LIMIT = 600
DATA_PER_TYPE_CAP = 120
# Cap inlined edges too: 500 dense repo nodes can carry 6k+ edges, and SVG (one element per
# edge, redrawn on pan/zoom) chokes past ~1-2k. Keep the highest-weighted edges only.
LINK_LIMIT = 1200

# How many structured entities per mapped type get their own wiki page. Kept >= the
# portal's per-type cap so any node the portal can render also has a page.
WIKI_PER_TYPE_CAP = 250

_DEFAULT_PREDICATE_WEIGHT = 4
# Priority for structured/business mapped types, which are plain strings (not EntityType).
_DATA_TYPE_PRIORITY = {
    "League": 9,
    "Team": 8,
    "Market": 7,
    "ModelArtifact": 7,
    "Bet": 6,
    "Prediction": 6,
    "Match": 6,
    "Player": 5,
}
_TYPE_PRIORITY: dict[str, int] = {
    **{entity_type.value: weight for entity_type, weight in TYPE_WEIGHTS.items()},
    **_DATA_TYPE_PRIORITY,
}

Node = dict[str, object]
Link = dict[str, object]


def _display_type(node: Node) -> str:
    return str(node.get("visual_type") or node.get("mapped_type") or node.get("type") or "")


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
    pinned_ids: frozenset[str] = frozenset(),
    link_limit: int | None = None,
) -> tuple[list[Node], list[Link]]:
    """Return the top-``limit`` nodes (by weighted degree + type priority) and their links.

    Pinned nodes (e.g. endpoints of curated key relationships) always survive. When
    ``per_type_cap`` is set, each mapped type is capped before the global cut so a
    high-cardinality type cannot crowd out the rest of the graph.
    """
    weighted = _weighted_degree(nodes, links)

    def score(node: Node) -> float:
        base = weighted.get(str(node["id"]), 0.0) + _TYPE_PRIORITY.get(_display_type(node), 0)
        return base + (1_000_000 if str(node["id"]) in pinned_ids else 0)

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
        for assertion, subject, object_ in items:
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
