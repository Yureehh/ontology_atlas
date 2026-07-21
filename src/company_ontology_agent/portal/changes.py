"""Shape a :class:`GraphDiff` into the bounded JSON payload the Changes tab renders.

Mirrors :mod:`portal.intelligence`: pure shaping with wiki deep-links resolved and every
list capped so ``changes.html`` stays small and offline-openable. The full diff is never
inlined wholesale; per-section totals convey what was truncated.
"""

from __future__ import annotations

from typing import Any

from company_ontology_agent.graph.diffing import GraphDiff
from company_ontology_agent.graph.models import Entity
from company_ontology_agent.utils.ids import slugify

_LIST_CAP = 50


def _wiki(name: str, entity_id: str, page_ids: set[str]) -> str | None:
    return f"../wiki/entities/{slugify(name)}.html" if entity_id in page_ids else None


def _entity_row(entity: Entity, page_ids: set[str]) -> dict[str, Any]:
    return {
        "name": entity.name,
        "type": entity.type.value,
        "community": entity.community,
        "wiki_url": _wiki(entity.name, entity.id, page_ids),
    }


def shape_changes(
    diff: GraphDiff,
    page_ids: set[str],
    name_by_id: dict[str, str],
) -> dict[str, Any]:
    """Return the Changes-tab payload. ``has_baseline=False`` → caller renders the empty state."""
    if not diff.has_baseline:
        return {"has_baseline": False}

    def rel(assertion: Any) -> dict[str, Any]:
        source = name_by_id.get(assertion.subject_id, assertion.subject_id)
        target = name_by_id.get(assertion.object_id, assertion.object_id)
        return {
            "source": source,
            "predicate": assertion.predicate,
            "target": target,
            "source_wiki": _wiki(source, assertion.subject_id, page_ids),
            "target_wiki": _wiki(target, assertion.object_id, page_ids),
        }

    return {
        "has_baseline": True,
        "summary": {
            "entities_added": len(diff.entities_added),
            "entities_removed": len(diff.entities_removed),
            "entities_modified": len(diff.entities_modified),
            "relationships_added": len(diff.assertions_added),
            "relationships_removed": len(diff.assertions_removed),
            "communities_changed": len(diff.communities_changed),
        },
        "entities_added": [_entity_row(e, page_ids) for e in diff.entities_added[:_LIST_CAP]],
        "entities_removed": [_entity_row(e, page_ids) for e in diff.entities_removed[:_LIST_CAP]],
        "entities_modified": [
            {
                "name": change.name,
                "type": change.type,
                "changes": [
                    {"field": field, "old": old, "new": new}
                    for field, (old, new) in change.fields.items()
                ],
                "wiki_url": _wiki(change.name, change.id, page_ids),
            }
            for change in diff.entities_modified[:_LIST_CAP]
        ],
        "relationships_added": [rel(a) for a in diff.assertions_added[:_LIST_CAP]],
        "relationships_removed": [rel(a) for a in diff.assertions_removed[:_LIST_CAP]],
        "communities_changed": [
            delta.model_dump() for delta in diff.communities_changed[:_LIST_CAP]
        ],
        "cohesion_deltas": [delta.model_dump() for delta in diff.cohesion_deltas[:_LIST_CAP]],
    }
