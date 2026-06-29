from __future__ import annotations

from pathlib import Path

from company_ontology_agent.graph.diffing import diff_graphs
from company_ontology_agent.graph.models import (
    Assertion,
    Entity,
    EntityType,
    ExtractedGraph,
)
from company_ontology_agent.graph.repository import JsonGraphRepository
from company_ontology_agent.utils.ids import stable_id


def _entity(name: str, etype: EntityType = EntityType.module, **kw: object) -> Entity:
    return Entity(
        id=stable_id("entity", name.lower(), etype.value),
        type=etype,
        name=name,
        normalized_name=name.lower(),
        description=kw.get("description"),  # type: ignore[arg-type]
        community=kw.get("community"),  # type: ignore[arg-type]
    )


def _assertion(subject: Entity, predicate: str, obj: Entity) -> Assertion:
    return Assertion(
        id=stable_id("assertion", subject.id, predicate, obj.id, ""),
        predicate=predicate,
        subject_id=subject.id,
        object_id=obj.id,
        evidence_span_id="",
        confidence=0.9,
        extractor="test",
    )


def test_diff_detects_added_removed_modified() -> None:
    a, b, c = _entity("Alpha"), _entity("Beta"), _entity("Gamma")
    prev = ExtractedGraph(project_slug="p", entities=[a, b], assertions=[_assertion(a, "uses", b)])
    # Gamma added, Beta removed; Alpha keeps its id but gains a description (= modified).
    a2 = _entity("Alpha", description="now documented")
    current = ExtractedGraph(
        project_slug="p", entities=[a2, c], assertions=[_assertion(a2, "uses", c)]
    )

    diff = diff_graphs(prev, current)
    assert diff.has_baseline
    assert [e.name for e in diff.entities_added] == ["Gamma"]
    assert [e.name for e in diff.entities_removed] == ["Beta"]
    assert [c.name for c in diff.entities_modified] == ["Alpha"]
    assert diff.entities_modified[0].fields["description"] == (None, "now documented")
    assert len(diff.assertions_added) == 1
    assert len(diff.assertions_removed) == 1


def test_diff_without_baseline() -> None:
    current = ExtractedGraph(project_slug="p", entities=[_entity("Alpha")])
    diff = diff_graphs(None, current)
    assert diff.has_baseline is False
    assert diff.entities_added == []


def test_cohesion_and_community_deltas() -> None:
    current = ExtractedGraph(project_slug="p")
    prev_analysis = {"communities": {"0": [1, 2, 3]}, "cohesion": {"0": 0.20}}
    cur_analysis = {"communities": {"0": [1, 2, 3, 4, 5]}, "cohesion": {"0": 0.55}}
    diff = diff_graphs(ExtractedGraph(project_slug="p"), current, prev_analysis, cur_analysis)
    assert diff.communities_changed[0].delta == 2
    assert diff.cohesion_deltas[0].old == 0.20 and diff.cohesion_deltas[0].new == 0.55


def test_snapshot_previous_round_trip(tmp_path: Path) -> None:
    repo = JsonGraphRepository(tmp_path / "graph.json")
    old = ExtractedGraph(project_slug="p", entities=[_entity("Old")])
    repo.replace_graph(old)
    repo.snapshot_previous()  # copy graph.json → graph.prev.json before overwrite
    repo.replace_graph(ExtractedGraph(project_slug="p", entities=[_entity("New")]))

    previous = repo.read_previous("p")
    assert previous is not None
    assert [e.name for e in previous.entities] == ["Old"]


def test_read_previous_returns_none_on_first_run(tmp_path: Path) -> None:
    repo = JsonGraphRepository(tmp_path / "graph.json")
    assert repo.read_previous("p") is None
