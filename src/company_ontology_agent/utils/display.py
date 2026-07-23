from __future__ import annotations

import re

from company_ontology_agent.graph.models import Entity, EntityType


def public_project_name(project_slug: str, project_name: str | None = None) -> str:
    candidate = (project_name or "").strip() or _title_from_slug(project_slug)
    candidate = re.sub(r"\bOntology\s+Atlas\b", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\bAtlas\s+Ontology\b", "Atlas", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\bOntology\b$", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\s+", " ", candidate).strip()
    return candidate or _title_from_slug(project_slug)


def public_entity_type(entity: Entity) -> str:
    mapped_type = str(entity.metadata.get("mapped_type") or "").strip()
    if mapped_type:
        return mapped_type
    if entity.type is EntityType.business_entity:
        return "Concept"
    return entity.type.value


def is_opaque_entity_name(name: str) -> bool:
    stripped = name.strip().lower()
    return bool(
        stripped.startswith(("oe:", "entity_"))
        or re.fullmatch(r"[0-9a-f-]{18,}", stripped)
        or re.search(r"[0-9a-f]{24,}", stripped)
    )


def is_test_entity(entity: Entity) -> bool:
    text = f"{entity.name} {entity.source_path or ''}".lower()
    return "/test" in text or "tests/" in text or entity.name.lower().startswith("test_")


def _title_from_slug(project_slug: str) -> str:
    parts = re.split(r"[-_]+", project_slug)
    ignored = {"ontology", "atlas"}
    words = [part for part in parts if part and part.lower() not in ignored]
    return " ".join(word.capitalize() for word in words) or project_slug
