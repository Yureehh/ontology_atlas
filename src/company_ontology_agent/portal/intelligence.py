"""Shape Graphify's graph-intelligence analysis into a JSON payload for the portal.

Graphify already computes architectural hotspots ("god" nodes), surprising
connections, and per-community cohesion in ``.graphify_analysis.json`` but nothing
surfaced it. This turns that raw analysis into a dashboard-ready structure with wiki
deep links resolved where possible.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from company_ontology_agent.graph.models import Entity, ExtractedGraph
from company_ontology_agent.utils.ids import slugify

# A community needs at least this many members before low cohesion is worth flagging.
_MIN_REFACTOR_SIZE = 5


def _wiki_url(entity: Entity | None, page_ids: set[str]) -> str | None:
    if entity is not None and entity.id in page_ids:
        return f"../wiki/entities/{slugify(entity.name)}.html"
    return None


def _norm(label: object) -> str:
    return str(label).strip().removesuffix("()").strip().lower()


def build_intelligence(
    graph: ExtractedGraph,
    analysis: dict[str, Any] | None,
    *,
    page_ids: set[str],
    report_exists: bool,
) -> dict[str, Any] | None:
    """Return a JSON-serializable intelligence payload, or ``None`` if no analysis exists."""
    if not analysis:
        return None

    by_graphify = {entity.graphify_id: entity for entity in graph.entities if entity.graphify_id}
    by_name: dict[str, Entity] = {}
    community_labels: dict[str, str] = {}
    for entity in graph.entities:
        by_name.setdefault(_norm(entity.normalized_name), entity)
        by_name.setdefault(_norm(entity.name), entity)
        community_id = entity.metadata.get("community_id")
        if community_id is not None and entity.community:
            community_labels.setdefault(str(community_id), entity.community)

    def resolve(token: object) -> Entity | None:
        if token in by_graphify:
            return by_graphify[str(token)]
        return by_name.get(_norm(token))

    hotspots: list[dict[str, Any]] = []
    for god in analysis.get("gods", []):
        match = resolve(god.get("id"))
        hotspots.append(
            {
                "label": god.get("label") or god.get("id"),
                "degree": int(god.get("degree", 0)),
                "community": match.community if match else None,
                "wiki_url": _wiki_url(match, page_ids),
            }
        )
    hotspots.sort(key=lambda hotspot: int(hotspot["degree"]), reverse=True)

    surprises = []
    for surprise in analysis.get("surprises", []):
        source = resolve(surprise.get("source"))
        target = resolve(surprise.get("target"))
        surprises.append(
            {
                "source": surprise.get("source"),
                "target": surprise.get("target"),
                "relation": surprise.get("relation"),
                "confidence": surprise.get("confidence"),
                "why": surprise.get("why"),
                "source_files": surprise.get("source_files", []),
                "source_wiki": _wiki_url(source, page_ids),
                "target_wiki": _wiki_url(target, page_ids),
            }
        )

    communities_raw = analysis.get("communities", {}) or {}
    cohesion = analysis.get("cohesion", {}) or {}
    communities: list[dict[str, Any]] = []
    for community_id, members in communities_raw.items():
        member_entities = [by_graphify[m] for m in members if m in by_graphify]
        member_label = next((e.community for e in member_entities if e.community), None)
        communities.append(
            {
                "id": str(community_id),
                "label": community_labels.get(str(community_id))
                or member_label
                or f"Community {community_id}",
                "size": len(members),
                "cohesion": round(float(cohesion.get(str(community_id), 0.0)), 3),
                "members": [
                    {"name": entity.name, "wiki_url": _wiki_url(entity, page_ids)}
                    for entity in member_entities[:8]
                ],
            }
        )
    communities.sort(key=lambda community: int(community["size"]), reverse=True)

    refactor_candidates = _refactor_candidates(communities)
    questions = _suggested_questions(graph, hotspots, surprises, communities, page_ids)
    quality = _quality(graph)

    tokens = analysis.get("tokens", {}) or {}
    return {
        "hotspots": hotspots,
        "surprises": surprises,
        "communities": communities,
        "refactor_candidates": refactor_candidates,
        "questions": questions,
        "quality": quality,
        "tokens": {"input": tokens.get("input", 0), "output": tokens.get("output", 0)},
        "report_url": "../graphify-out/GRAPH_REPORT.md" if report_exists else None,
        "summary": {
            "community_count": len(communities_raw),
            "hotspot_count": len(hotspots),
            "surprise_count": len(surprises),
            "question_count": len(questions),
        },
    }


def _refactor_candidates(communities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sizeable communities with the lowest cohesion — loosely-knit, worth splitting."""
    sizeable = [c for c in communities if int(c["size"]) >= _MIN_REFACTOR_SIZE]
    sizeable.sort(key=lambda c: float(c["cohesion"]))
    return sizeable[:8]


def _suggested_questions(
    graph: ExtractedGraph,
    hotspots: list[dict[str, Any]],
    surprises: list[dict[str, Any]],
    communities: list[dict[str, Any]],
    page_ids: set[str],
) -> list[dict[str, Any]]:
    """Generate exploration questions + answers derived from the graph (no LLM, no tokens).

    Answers come from traversing Graphify's extracted graph in-process, so they are free,
    deterministic, and need no live service.
    """
    by_id = {entity.id: entity for entity in graph.entities}
    by_norm = {_norm(entity.name): entity for entity in graph.entities}
    incoming: dict[str, list[str]] = defaultdict(list)
    for assertion in graph.assertions:
        subject = by_id.get(assertion.subject_id)
        if subject is not None:
            incoming[assertion.object_id].append(subject.name)

    questions: list[dict[str, Any]] = []
    for hotspot in hotspots[:4]:
        entity = by_norm.get(_norm(hotspot["label"]))
        dependents = sorted(set(incoming.get(entity.id, []))) if entity else []
        if not dependents:
            continue
        shown = dependents[:6]
        more = f" (+{len(dependents) - len(shown)} more)" if len(dependents) > len(shown) else ""
        questions.append(
            {
                "question": f"What depends on {hotspot['label']}?",
                "answer": ", ".join(shown) + more,
                "wiki_url": _wiki_url(entity, page_ids),
            }
        )
    for surprise in surprises[:3]:
        if surprise.get("why"):
            questions.append(
                {
                    "question": (
                        f"Why does {surprise['source']} "
                        f"{surprise.get('relation') or 'connect to'} {surprise['target']}?"
                    ),
                    "answer": surprise["why"],
                    "wiki_url": surprise.get("source_wiki"),
                }
            )
    for community in communities[:3]:
        members = [m["name"] for m in community.get("members", [])][:6]
        if not members:
            continue
        questions.append(
            {
                "question": f"What is the {community['label']} community responsible for?",
                "answer": f"{community['size']} nodes incl. " + ", ".join(members),
                "wiki_url": None,
            }
        )
    return questions


def _quality(graph: ExtractedGraph) -> dict[str, Any]:
    """In-process data-quality signals over the relationships (duplicates, self-loops, multi-edges)."""
    triple_counts: Counter[tuple[str, str, str]] = Counter()
    pair_predicates: dict[tuple[str, str], set[str]] = defaultdict(set)
    self_loops = 0
    for assertion in graph.assertions:
        triple_counts[(assertion.subject_id, assertion.predicate, assertion.object_id)] += 1
        pair_predicates[(assertion.subject_id, assertion.object_id)].add(assertion.predicate)
        if assertion.subject_id == assertion.object_id:
            self_loops += 1
    duplicate_edges = sum(count - 1 for count in triple_counts.values() if count > 1)
    multi_edges = sum(1 for predicates in pair_predicates.values() if len(predicates) > 1)
    total = len(graph.assertions)
    return {
        "total_relationships": total,
        "duplicate_edges": duplicate_edges,
        "multi_edge_pairs": multi_edges,
        "self_loops": self_loops,
        "clean": duplicate_edges == 0 and self_loops == 0,
    }
