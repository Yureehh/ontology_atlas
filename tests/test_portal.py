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
from company_ontology_agent.portal.intelligence import build_intelligence


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
        "ask.html",
        "explore.html",
        "intelligence.html",
        "changes.html",
        "graph.json",
    } <= names
    assert (tmp_path / "portal" / "index.html").exists()
    assert not (tmp_path / "portal" / "trust.html").exists()


def test_index_redirects_to_answer_first_page(tmp_path: Path) -> None:
    PortalBuilder().build(_sample_graph(), tmp_path, tmp_path / "portal")
    index = (tmp_path / "portal" / "index.html").read_text(encoding="utf-8")
    assert "ask.html" in index
    assert 'id="portal-data"' not in index  # it's a redirect, not a full page


def test_ask_page_uses_project_golden_questions_as_suggestions(tmp_path: Path) -> None:
    rag = tmp_path / "rag"
    rag.mkdir()
    (rag / "questions.yaml").write_text(
        """questions:
  - id: impact
    question: Which prediction modules are affected?
    should_answer: true
  - id: evidence
    question: What evidence supports the prediction?
    should_answer: true
  - id: no-answer
    question: Which payroll platform is used?
    should_answer: false
""",
        encoding="utf-8",
    )

    PortalBuilder().build(_sample_graph(), tmp_path, tmp_path / "portal")
    ask_html = (tmp_path / "portal" / "ask.html").read_text(encoding="utf-8")
    payload = json.loads(re.search(r'id="portal-data">(.*?)</script>', ask_html, re.S).group(1))

    assert payload["suggested_questions"] == [
        "Which prediction modules are affected?",
        "What evidence supports the prediction?",
    ]


def test_ask_assets_render_markdown_and_bound_long_evidence() -> None:
    javascript = Path("src/company_ontology_agent/portal/assets/portal.js").read_text(
        encoding="utf-8"
    )
    css = Path("src/company_ontology_agent/portal/assets/portal.css").read_text(encoding="utf-8")

    assert "payload.answer_html" in javascript
    assert "Ready ·" not in javascript
    assert "status.hidden = ready" in javascript
    assert "overflow-wrap: anywhere" in css
    assert ".answer-grid > .card { min-width: 0" in css
    assert "grid-template-columns: minmax(320px, .82fr) minmax(0, 1.18fr)" in css
    assert (
        'const edge = document.createElementNS(SVGNS, crossGroup ? "path" : "line")'
        in javascript
    )


def test_search_index_is_bounded_to_visible_entities(tmp_path: Path) -> None:
    PortalBuilder().build(_sample_graph(), tmp_path, tmp_path / "portal")
    explore_page = (tmp_path / "portal" / "explore.html").read_text(encoding="utf-8")
    payload = json.loads(re.search(r'id="portal-data">(.*?)</script>', explore_page, re.S).group(1))
    assert len(payload["search_index"]) == len(payload["nodes"])
    assert len(payload["search_index"]) < 402


def test_changes_page_shows_empty_state_without_baseline(tmp_path: Path) -> None:
    PortalBuilder().build(_sample_graph(), tmp_path, tmp_path / "portal")
    changes_html = (tmp_path / "portal" / "changes.html").read_text(encoding="utf-8")
    payload = json.loads(re.search(r'id="portal-data">(.*?)</script>', changes_html, re.S).group(1))
    assert payload["page"] == "changes"
    assert payload["changes"]["has_baseline"] is False


def test_portal_removes_stale_trust_page_and_navigation(tmp_path: Path) -> None:
    portal = tmp_path / "portal"
    portal.mkdir()
    (portal / "trust.html").write_text("stale", encoding="utf-8")

    PortalBuilder().build(_sample_graph(), tmp_path, portal)

    explore = (portal / "explore.html").read_text(encoding="utf-8")
    assert not (portal / "trust.html").exists()
    assert "trust.html" not in explore
    assert ">Trust<" not in explore


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
    assert payload["changes"]["compatible"] is True
    assert payload["changes"]["summary"]["entities_added"] >= 1
    groups = payload["changes"]["entity_groups_added"]
    assert any(group["label"] == "oracle_bets_predictions · Prediction" for group in groups)
    assert all("Prediction 0" not in group["representatives"] for group in groups)
    assert payload["changes"]["summary"]["business_records_added"] == 1
    assert payload["changes"]["summary"]["architecture_entities_added"] == 0
    assert any(
        item["name"] == "Predictor" and item["direction"] == "upstream"
        for item in payload["changes"]["affected_components"]
    )


def test_changes_suppress_derived_community_only_drift() -> None:
    from company_ontology_agent.graph.diffing import EntityChange, GraphDiff
    from company_ontology_agent.portal.changes import shape_changes

    changes = shape_changes(
        GraphDiff(
            entities_modified=[
                EntityChange(
                    id="mod",
                    name="Predictor",
                    type=EntityType.module.value,
                    fields={"community": ("Area A", "Area B")},
                )
            ]
        ),
        _sample_graph().entities,
        _sample_graph().entities,
    )

    assert changes["summary"]["entities_modified"] == 0
    assert changes["modified_components"] == []


def test_changes_refuses_incompatible_ingestion_scopes(tmp_path: Path) -> None:
    current = _sample_graph()
    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True)
    (tmp_path / "project.yaml").write_text("project_slug: demo\nproject_name: Demo\n")
    (processed / "graph.prev.json").write_text(current.model_dump_json(), encoding="utf-8")
    (processed / "scope-fingerprint.json").write_text('{"digest":"new"}', encoding="utf-8")
    (processed / "scope-fingerprint.prev.json").write_text(
        '{"digest":"old"}', encoding="utf-8"
    )

    PortalBuilder().build(current, tmp_path, tmp_path / "portal")
    html = (tmp_path / "portal" / "changes.html").read_text(encoding="utf-8")
    payload = json.loads(re.search(r'id="portal-data">(.*?)</script>', html, re.S).group(1))
    assert payload["changes"]["compatible"] is False
    assert "summary" not in payload["changes"]


def test_inline_payload_is_bounded(tmp_path: Path) -> None:
    PortalBuilder().build(_sample_graph(), tmp_path, tmp_path / "portal")
    explore_page = (tmp_path / "portal" / "explore.html").read_text(encoding="utf-8")
    payload = json.loads(re.search(r'id="portal-data">(.*?)</script>', explore_page, re.S).group(1))
    # 400 prediction rows must be pruned to the per-type cap, not inlined wholesale.
    assert len(payload["nodes"]) <= ranking.DATA_LIMIT + ranking.ARCHITECTURE_LIMIT
    assert payload["stats"]["total_nodes"] == 402
    assert payload["page"] == "explore" and payload["kind"] == "repo"
    assert "shown_nodes: view.nodes.length" in explore_page
    assert "relayout(); renderLegend();" in explore_page
    # The whole page stays small enough to open offline.
    assert len(explore_page.encode("utf-8")) < 1_000_000


def test_explore_defaults_to_architecture_aggregates_and_named_business_entities(
    tmp_path: Path,
) -> None:
    graph = _sample_graph()
    graph.entities.extend(
        _entity(
            f"module-{index}",
            f"Module {index}",
            EntityType.module,
            community=f"Area {index}",
        )
        for index in range(60)
    )

    PortalBuilder().build(graph, tmp_path, tmp_path / "portal")
    explore_page = (tmp_path / "portal" / "explore.html").read_text(encoding="utf-8")
    payload = json.loads(re.search(r'id="portal-data">(.*?)</script>', explore_page, re.S).group(1))

    architecture = [node for node in payload["nodes"] if node["graph_kind"] == "repo"]
    data = [node for node in payload["nodes"] if node["graph_kind"] == "data"]
    assert len(architecture) <= 30
    assert all(node["visual_type"] == "ArchitectureGroup" for node in architecture)
    assert all(node["member_count"] >= 1 for node in architecture)
    assert {node["mapped_type"] for node in data} == {"Prediction"}
    assert 1 < len(data) <= ranking.DATA_PER_TYPE_CAP
    assert "BusinessEntity" not in explore_page
    assert all(node["type"] != "BusinessEntity" for node in data)
    assert all(node["name"].startswith("Prediction ") for node in data)
    assert all("member_count" not in node for node in data)


def test_architecture_groups_follow_package_boundaries_before_communities() -> None:
    nodes = [
        {
            "id": "orders-api",
            "name": "Orders API",
            "type": "Module",
            "visual_type": "Module",
            "graph_kind": "repo",
            "source_path": "packages/orders/src/api.py",
            "community": "Mixed generated community",
        },
        {
            "id": "orders-model",
            "name": "Order",
            "type": "Class",
            "visual_type": "Class",
            "graph_kind": "repo",
            "source_path": "packages/orders/src/models.py",
            "community": "Another community",
        },
        {
            "id": "billing",
            "name": "Billing",
            "type": "Module",
            "visual_type": "Module",
            "graph_kind": "repo",
            "source_path": "packages/billing/src/service.py",
            "community": "Mixed generated community",
        },
    ]
    links = [
        {
            "id": "dep",
            "source": "orders-api",
            "target": "billing",
            "predicate": "depends_on",
        }
    ]

    aggregates, aggregate_links = ranking.aggregate_explore(nodes, links)
    architecture = [node for node in aggregates if node["graph_kind"] == "repo"]

    assert {node["name"] for node in architecture} == {"Orders", "Billing"}
    assert next(node for node in architecture if node["name"] == "Orders")["member_count"] == 2
    assert len(aggregate_links) == 1


def test_architecture_overview_hides_tests_generated_paths_and_unresolved_libraries() -> None:
    nodes = [
        {
            "id": "app",
            "name": "app.py",
            "type": "File",
            "graph_kind": "repo",
            "source_path": "services/api/app.py",
        },
        {
            "id": "test",
            "name": "test_app.py",
            "type": "File",
            "graph_kind": "repo",
            "source_path": "tests/test_app.py",
        },
        {
            "id": "log",
            "name": "README.md",
            "type": "File",
            "graph_kind": "repo",
            "source_path": "logs/README.md",
        },
        {
            "id": "external",
            "name": "RuntimeError",
            "type": "Class",
            "graph_kind": "repo",
            "source_path": None,
        },
    ]

    overview, _ = ranking.aggregate_explore(nodes, [])

    assert [node["name"] for node in overview] == ["Api"]


def test_portal_assets_use_directional_architecture_and_faceted_filters() -> None:
    javascript = Path("src/company_ontology_agent/portal/assets/portal.js").read_text(
        encoding="utf-8"
    )

    assert "layoutArchitecture" in javascript
    assert 'document.createElementNS(SVGNS, "rect")' in javascript
    assert "refreshFacets" in javascript
    assert "optionCounts" in javascript
    assert "architecture-breadcrumbs" in javascript
    assert 'classList.remove("details-collapsed")' in javascript
    assert 'getElementById("show-details").hidden = false' in javascript


def test_business_data_plot_uses_real_league_and_team_names(tmp_path: Path) -> None:
    graph = _sample_graph()
    graph.entities.extend(
        [
            _entity(
                "lpl",
                "LPL",
                EntityType.business_entity,
                connector="parquet",
                dataset="matches",
                mapped_type="League",
            ),
            _entity(
                "lck",
                "LCK",
                EntityType.business_entity,
                connector="parquet",
                dataset="matches",
                mapped_type="League",
            ),
            _entity(
                "blg",
                "Bilibili Gaming",
                EntityType.business_entity,
                connector="parquet",
                dataset="matches",
                mapped_type="Team",
            ),
        ]
    )
    graph.assertions.append(_assertion("blg-lpl", "blg", "lpl", "team_in_league"))

    PortalBuilder().build(graph, tmp_path, tmp_path / "portal")
    explore_page = (tmp_path / "portal" / "explore.html").read_text(encoding="utf-8")
    payload = json.loads(re.search(r'id="portal-data">(.*?)</script>', explore_page, re.S).group(1))
    data_names = {
        node["name"] for node in payload["nodes"] if node["graph_kind"] == "data"
    }

    assert {"LPL", "LCK", "Bilibili Gaming"} <= data_names
    assert "League" not in data_names
    assert "Team" not in data_names


def test_insights_are_measurable_and_avoid_speculative_refactor_claims() -> None:
    graph = _sample_graph()
    graph.entities[0].community = "Platform"
    graph.entities[1].community = "Prediction"

    insights = build_intelligence(graph, report_exists=False)

    assert insights is not None
    assert insights["impact_hotspots"]
    assert insights["cross_boundaries"]
    assert insights["data_lineage"]
    assert "refactor_candidates" not in insights
    assert "surprises" not in insights
    assert "recommendations" not in insights


def test_insights_page_does_not_render_recommended_next_checks(tmp_path: Path) -> None:
    PortalBuilder().build(_sample_graph(), tmp_path, tmp_path / "portal")
    html = (tmp_path / "portal" / "intelligence.html").read_text(encoding="utf-8")

    assert "Recommended next checks" not in html


def test_insights_filter_generic_symbols_and_trivial_boundary_links() -> None:
    graph = _sample_graph()
    graph.entities.extend(
        [
            _entity("any", "Any", EntityType.class_, community="External"),
            _entity("series", "Series", EntityType.class_, community="External"),
            _entity("workflow", "DailyWorkflow", EntityType.class_, community="Workflow"),
        ]
    )
    graph.assertions.extend(
        [
            _assertion("generic-hotspot-1", "any", "mod", "uses"),
            _assertion("generic-hotspot-2", "series", "mod", "uses"),
            _assertion("trivial-boundary", "workflow", "mod", "contains"),
            _assertion("meaningful-boundary", "workflow", "mod", "uses"),
        ]
    )

    insights = build_intelligence(graph, report_exists=False)

    assert "Any" not in {item["name"] for item in insights["impact_hotspots"]}
    assert "Series" not in {item["name"] for item in insights["impact_hotspots"]}
    assert all(item["predicate"] != "contains" for item in insights["cross_boundaries"])
    assert any(item["predicate"] == "uses" for item in insights["cross_boundaries"])


def test_prune_layer_caps_links() -> None:
    # A star of 5 edges capped to 2 — guards the SVG-melting edge explosion.
    nodes = [{"id": f"n{i}", "name": f"n{i}", "type": "File"} for i in range(6)]
    links = [{"source": "n0", "target": f"n{i}", "predicate": "calls"} for i in range(1, 6)]
    _, kept = ranking.prune_layer(nodes, links, limit=10, link_limit=2)
    assert len(kept) == 2


def test_full_graph_json_keeps_everything(tmp_path: Path) -> None:
    PortalBuilder().build(_sample_graph(), tmp_path, tmp_path / "portal")
    full = json.loads((tmp_path / "portal" / "graph.json").read_text(encoding="utf-8"))
    assert len(full["nodes"]) == 402
    module = next(node for node in full["nodes"] if node["id"] == "mod")
    assert module["wiki"] == "../wiki/modules/predictor.html"


def test_page_worthy_ids_keep_all_repo_entities() -> None:
    graph = _sample_graph()
    ids = ranking.page_worthy_entity_ids(graph)
    assert "sys" in ids and "mod" in ids
    structured_pages = sum(1 for e in graph.entities if e.id.startswith("pred-") and e.id in ids)
    # Bounded by the per-type cap (plus a few key-relationship endpoints), never all 400 rows.
    assert structured_pages <= ranking.WIKI_PER_TYPE_CAP + 10
    assert structured_pages < 400
