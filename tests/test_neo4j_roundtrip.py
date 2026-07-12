from __future__ import annotations

from company_ontology_agent.graph.models import Entity, EntityType
from company_ontology_agent.graph.repository import _from_neo4j_props, _neo4j_props


def test_metadata_survives_neo4j_props_roundtrip() -> None:
    # Neo4j can't store nested dicts, so metadata is flattened to metadata_json on
    # write; reading it back must restore the dict or the portal/wiki lose
    # mapped_type and every structured row degrades to a generic BusinessEntity.
    entity = Entity(
        id="e1",
        type=EntityType.business_entity,
        name="T1",
        normalized_name="t1",
        metadata={"mapped_type": "Team", "dataset": "oracle_bets_lol_raw", "domain": "betting"},
    )
    stored = _neo4j_props(entity.model_dump(mode="json"))
    assert "metadata_json" in stored and "metadata" not in stored

    restored = Entity.model_validate(_from_neo4j_props(stored))
    assert restored.metadata["mapped_type"] == "Team"
    assert restored.metadata["dataset"] == "oracle_bets_lol_raw"


def test_from_neo4j_props_leaves_plain_values_alone() -> None:
    props = {"id": "x", "name": "N", "count": 3, "broken_json": "{not json"}
    restored = _from_neo4j_props(props)
    assert restored["id"] == "x" and restored["count"] == 3
    assert restored["broken_json"] == "{not json"  # unparseable stays as-is
