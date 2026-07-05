from __future__ import annotations

import json
import re
from pathlib import Path

from company_ontology_agent.graph.models import (
    Assertion,
    Entity,
    EntityType,
    ExtractedGraph,
)
from company_ontology_agent.portal import ranking
from company_ontology_agent.portal.builder import PortalBuilder


def _entity(eid: str, name: str, etype: EntityType, **metadata: object) -> Entity:
    return Entity(
        id=eid,
        type=etype,
        name=name,
        normalized_name=name.lower(),
        extraction_source=str(metadata.pop("extraction_source", "graphify")),
        metadata=metadata,  # type: ignore[arg-type]
    )


def _assertion(aid: str, subject: str, obj: str, predicate: str = "uses") -> Assertion:
    return Assertion(
        id=aid,
        predicate=predicate,
        subject_id=subject,
        object_id=obj,
        evidence_span_id="",
        confidence=0.9,
        extractor="test",
    )


def _sample_graph() -> ExtractedGraph:
    entities: list[Entity] = [
        _entity("sys", "Platform", EntityType.system),
        _entity("mod", "Predictor", EntityType.module),
    ]
    assertions = [_assertion("a-sys-mod", "sys", "mod", "depends_on")]
    # Many structured "data" rows of a single mapped type to exercise per-type caps.
    for index in range(400):
        eid = f"pred-{index}"
        entities.append(
            _entity(
                eid,
                f"Prediction {index}",
                EntityType.business_entity,
                extraction_source="structured_connector",
                connector="parquet",
                dataset="oracle_bets_predictions",
                mapped_type="Prediction",
            )
        )
        assertions.append(_assertion(f"a-{index}", "mod", eid, "predicts"))
    return ExtractedGraph(project_slug="demo", entities=entities, assertions=assertions)


def test_portal_emits_all_pages_and_full_graph(tmp_path: Path) -> None:
    files = PortalBuilder().build(_sample_graph(), tmp_path, tmp_path / "portal")
    names = {path.name for path in files}
    assert {
        "index.html",
        "data-graph.html",
        "repo.html",
        "intelligence.html",
        "changes.html",
        "graph.json",
    } <= names
    assert (tmp_path / "portal" / "index.html").exists()


def test_index_redirects_to_populated_layer(tmp_path: Path) -> None:
    # The sample graph is data-heavy (400 data nodes vs 2 repo), so the landing page
    # should forward to the data layer, not sit on an empty tab.
    PortalBuilder().build(_sample_graph(), tmp_path, tmp_path / "portal")
    index = (tmp_path / "portal" / "index.html").read_text(encoding="utf-8")
    assert "data-graph.html" in index
    assert 'id="portal-data"' not in index  # it's a redirect, not a full page


def test_search_index_covers_every_layer_entity(tmp_path: Path) -> None:
    PortalBuilder().build(_sample_graph(), tmp_path, tmp_path / "portal")
    data_page = (tmp_path / "portal" / "data-graph.html").read_text(encoding="utf-8")
    payload = json.loads(re.search(r'id="portal-data">(.*?)</script>', data_page, re.S).group(1))
    # Search must reach all 400 data entities even though only a ranked subset is plotted.
    assert len(payload["search_index"]) == 400
    assert len(payload["nodes"]) < len(payload["search_index"])


def test_changes_page_shows_empty_state_without_baseline(tmp_path: Path) -> None:
    PortalBuilder().build(_sample_graph(), tmp_path, tmp_path / "portal")
    changes_html = (tmp_path / "portal" / "changes.html").read_text(encoding="utf-8")
    payload = json.loads(re.search(r'id="portal-data">(.*?)</script>', changes_html, re.S).group(1))
    assert payload["page"] == "changes"
    assert payload["changes"]["has_baseline"] is False


def test_changes_page_reports_diff_against_baseline(tmp_path: Path) -> None:
    current = _sample_graph()
    baseline = current.model_copy(deep=True)
    baseline.entities = [e for e in baseline.entities if e.id != "pred-0"]  # baseline lacks pred-0
    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True)
    (processed / "graph.prev.json").write_text(baseline.model_dump_json(), encoding="utf-8")

    PortalBuilder().build(current, tmp_path, tmp_path / "portal")
    changes_html = (tmp_path / "portal" / "changes.html").read_text(encoding="utf-8")
    payload = json.loads(re.search(r'id="portal-data">(.*?)</script>', changes_html, re.S).group(1))
    assert payload["changes"]["has_baseline"] is True
    assert payload["changes"]["summary"]["entities_added"] >= 1
    added_names = {row["name"] for row in payload["changes"]["entities_added"]}
    assert "Prediction 0" in added_names


def test_inline_payload_is_bounded(tmp_path: Path) -> None:
    PortalBuilder().build(_sample_graph(), tmp_path, tmp_path / "portal")
    data_page = (tmp_path / "portal" / "data-graph.html").read_text(encoding="utf-8")
    payload = json.loads(re.search(r'id="portal-data">(.*?)</script>', data_page, re.S).group(1))
    # 400 prediction rows must be pruned to the per-type cap, not inlined wholesale.
    assert len(payload["nodes"]) <= ranking.DATA_LIMIT
    assert payload["stats"]["total_nodes"] == 400  # data layer only
    assert payload["page"] == "data" and payload["kind"] == "data"
    # The whole page stays small enough to open offline.
    assert len(data_page.encode("utf-8")) < 1_000_000


def test_full_graph_json_keeps_everything(tmp_path: Path) -> None:
    PortalBuilder().build(_sample_graph(), tmp_path, tmp_path / "portal")
    full = json.loads((tmp_path / "portal" / "graph.json").read_text(encoding="utf-8"))
    assert len(full["nodes"]) == 402


def test_page_worthy_ids_keep_all_repo_entities() -> None:
    graph = _sample_graph()
    ids = ranking.page_worthy_entity_ids(graph)
    assert "sys" in ids and "mod" in ids
    structured_pages = sum(1 for e in graph.entities if e.id.startswith("pred-") and e.id in ids)
    # Bounded by the per-type cap (plus a few key-relationship endpoints), never all 400 rows.
    assert structured_pages <= ranking.WIKI_PER_TYPE_CAP + 10
    assert structured_pages < 400
