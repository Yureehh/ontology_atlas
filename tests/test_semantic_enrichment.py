from company_ontology_agent.graph.models import Assertion, Entity, EntityType, ExtractedGraph
from company_ontology_agent.workflows.semantic_enrichment import build_semantic_enrichment


def test_semantic_enrichment_links_architecture_to_domain_without_copying_rows() -> None:
    architecture = ExtractedGraph(
        project_slug="oracle",
        entities=[
            Entity(
                id="loader",
                type=EntityType.class_,
                name="LeagueRatingsLoader",
                normalized_name="league ratings loader",
                source_path="models/lol/league_elo.py",
                extraction_source="graphify_ast",
            )
        ],
    )
    data = ExtractedGraph(
        project_slug="oracle",
        entities=[
            Entity(
                id="league-summary",
                type=EntityType.concept,
                name="Leagues in ratings",
                normalized_name="leagues in ratings",
                extraction_source="structured_connector",
                metadata={
                    "domain": "league_of_legends",
                    "dataset": "ratings",
                    "mapped_type": "League",
                    "semantic_summary": True,
                    "authority": "authoritative",
                },
            ),
            Entity(
                id="lpl",
                type=EntityType.business_entity,
                name="LPL",
                normalized_name="lpl",
                extraction_source="structured_connector",
                metadata={
                    "domain": "league_of_legends",
                    "mapped_type": "League",
                    "record_key": "lpl",
                    "connector": "parquet",
                },
            )
        ],
        assertions=[
            Assertion(
                id="league-member",
                predicate="member_of",
                subject_id="lpl",
                object_id="league-summary",
                evidence_span_id="",
                confidence=1.0,
                extractor="structured_connector",
                extraction_source="structured_connector",
            )
        ],
    )

    enriched = build_semantic_enrichment(architecture, data)

    assert enriched.entities == []
    assert len(enriched.assertions) == 1
    assertion = enriched.assertions[0]
    assert assertion.subject_id == "loader"
    assert assertion.object_id == "league-summary"
    assert assertion.predicate == "relates_to_domain"
    assert assertion.extraction_source == "semantic_enrichment"
    assert assertion.confidence_tier == "interpretive"
    combined = data.assertions + enriched.assertions
    assert any(
        item.subject_id == "lpl" and item.object_id == "league-summary" for item in combined
    )
    assert any(
        item.subject_id == "loader" and item.object_id == "league-summary" for item in combined
    )


def test_semantic_enrichment_is_globally_bounded() -> None:
    architecture = ExtractedGraph(
        project_slug="oracle",
        entities=[
            Entity(
                id=f"league-{index}",
                type=EntityType.file,
                name=f"league_{index}.py",
                normalized_name=f"league {index}",
            )
            for index in range(20)
        ],
    )
    data = ExtractedGraph(
        project_slug="oracle",
        entities=[
            Entity(
                id="league-summary",
                type=EntityType.concept,
                name="Leagues in ratings",
                normalized_name="leagues in ratings",
                extraction_source="structured_connector",
                metadata={"mapped_type": "League", "semantic_summary": True},
            ),
            Entity(
                id="league-row",
                type=EntityType.business_entity,
                name="LPL",
                normalized_name="lpl",
                extraction_source="structured_connector",
                metadata={"mapped_type": "League", "connector": "parquet"},
            )
        ],
    )

    enriched = build_semantic_enrichment(architecture, data, max_links=5)

    assert len(enriched.assertions) == 5
