"""Run-to-run graph diffing.

Compares two :class:`ExtractedGraph` snapshots by stable id to answer "what changed since
last run". Entity/Assertion ids are deterministic SHA256 hashes (see :mod:`utils.ids`), so a
node keeps its id across runs unless its name or type changes — which makes added/removed/
modified detection reliable. A rename therefore shows up as a remove + an add (documented).

Pure module: no I/O, no subprocess. The caller loads the prev/current graphs and the prev/
current Graphify analysis dicts and passes them in.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from company_ontology_agent.graph.models import Assertion, Entity, ExtractedGraph

# Entity fields whose change (while the id stays stable) counts as a "modification".
_TRACKED_FIELDS = ("description", "community", "source_path")


class EntityChange(BaseModel):
    id: str
    name: str
    type: str
    fields: dict[str, tuple[str | None, str | None]] = Field(default_factory=dict)


class CommunityDelta(BaseModel):
    id: str
    label: str
    old_size: int
    new_size: int
    delta: int


class CohesionDelta(BaseModel):
    id: str
    label: str
    old: float
    new: float


class GraphDiff(BaseModel):
    has_baseline: bool = True
    entities_added: list[Entity] = Field(default_factory=list)
    entities_removed: list[Entity] = Field(default_factory=list)
    entities_modified: list[EntityChange] = Field(default_factory=list)
    assertions_added: list[Assertion] = Field(default_factory=list)
    assertions_removed: list[Assertion] = Field(default_factory=list)
    communities_changed: list[CommunityDelta] = Field(default_factory=list)
    cohesion_deltas: list[CohesionDelta] = Field(default_factory=list)


def _community_labels(graph: ExtractedGraph) -> dict[str, str]:
    labels: dict[str, str] = {}
    for entity in graph.entities:
        community_id = entity.metadata.get("community_id")
        if community_id is not None and entity.community:
            labels.setdefault(str(community_id), entity.community)
    return labels


def _entity_modifications(old: Entity, new: Entity) -> dict[str, tuple[str | None, str | None]]:
    changes: dict[str, tuple[str | None, str | None]] = {}
    for field in _TRACKED_FIELDS:
        before = getattr(old, field)
        after = getattr(new, field)
        if before != after:
            changes[field] = (
                None if before is None else str(before),
                None if after is None else str(after),
            )
    return changes


def diff_graphs(
    prev: ExtractedGraph | None,
    current: ExtractedGraph,
    prev_analysis: dict[str, Any] | None = None,
    current_analysis: dict[str, Any] | None = None,
) -> GraphDiff:
    """Diff ``current`` against ``prev`` by stable id. ``prev is None`` → no-baseline result."""
    if prev is None:
        return GraphDiff(has_baseline=False)

    prev_entities = {entity.id: entity for entity in prev.entities}
    cur_entities = {entity.id: entity for entity in current.entities}
    added = [cur_entities[i] for i in cur_entities.keys() - prev_entities.keys()]
    removed = [prev_entities[i] for i in prev_entities.keys() - cur_entities.keys()]
    modified: list[EntityChange] = []
    for entity_id in cur_entities.keys() & prev_entities.keys():
        fields = _entity_modifications(prev_entities[entity_id], cur_entities[entity_id])
        if fields:
            entity = cur_entities[entity_id]
            modified.append(
                EntityChange(id=entity.id, name=entity.name, type=entity.type.value, fields=fields)
            )

    prev_assertions = {a.id: a for a in prev.assertions}
    cur_assertions = {a.id: a for a in current.assertions}
    added_ids = cur_assertions.keys() - prev_assertions.keys()
    removed_ids = prev_assertions.keys() - cur_assertions.keys()
    assertions_added = [cur_assertions[i] for i in added_ids]
    assertions_removed = [prev_assertions[i] for i in removed_ids]

    communities_changed, cohesion_deltas = _analysis_deltas(
        prev_analysis, current_analysis, _community_labels(current)
    )

    return GraphDiff(
        entities_added=sorted(added, key=lambda e: e.name),
        entities_removed=sorted(removed, key=lambda e: e.name),
        entities_modified=sorted(modified, key=lambda c: c.name),
        assertions_added=assertions_added,
        assertions_removed=assertions_removed,
        communities_changed=communities_changed,
        cohesion_deltas=cohesion_deltas,
    )


def _analysis_deltas(
    prev_analysis: dict[str, Any] | None,
    current_analysis: dict[str, Any] | None,
    labels: dict[str, str],
) -> tuple[list[CommunityDelta], list[CohesionDelta]]:
    if not prev_analysis or not current_analysis:
        return [], []
    prev_comm = prev_analysis.get("communities", {}) or {}
    cur_comm = current_analysis.get("communities", {}) or {}
    prev_coh = prev_analysis.get("cohesion", {}) or {}
    cur_coh = current_analysis.get("cohesion", {}) or {}

    community_deltas: list[CommunityDelta] = []
    for community_id in cur_comm.keys() & prev_comm.keys():
        old_size = len(prev_comm[community_id])
        new_size = len(cur_comm[community_id])
        if old_size != new_size:
            community_deltas.append(
                CommunityDelta(
                    id=str(community_id),
                    label=labels.get(str(community_id)) or f"Community {community_id}",
                    old_size=old_size,
                    new_size=new_size,
                    delta=new_size - old_size,
                )
            )
    community_deltas.sort(key=lambda d: abs(d.delta), reverse=True)

    cohesion_deltas: list[CohesionDelta] = []
    for community_id in cur_coh.keys() & prev_coh.keys():
        old = round(float(prev_coh[community_id]), 4)
        new = round(float(cur_coh[community_id]), 4)
        if abs(new - old) >= 0.005:
            cohesion_deltas.append(
                CohesionDelta(
                    id=str(community_id),
                    label=labels.get(str(community_id)) or f"Community {community_id}",
                    old=old,
                    new=new,
                )
            )
    cohesion_deltas.sort(key=lambda d: abs(d.new - d.old), reverse=True)
    return community_deltas, cohesion_deltas
