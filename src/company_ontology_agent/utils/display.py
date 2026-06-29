from __future__ import annotations

import re


def public_project_name(project_slug: str, project_name: str | None = None) -> str:
    candidate = (project_name or "").strip() or _title_from_slug(project_slug)
    candidate = re.sub(r"\bOntology\s+Atlas\b", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\bAtlas\s+Ontology\b", "Atlas", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\bOntology\b$", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\s+", " ", candidate).strip()
    return candidate or _title_from_slug(project_slug)


def _title_from_slug(project_slug: str) -> str:
    parts = re.split(r"[-_]+", project_slug)
    ignored = {"ontology", "atlas"}
    words = [part for part in parts if part and part.lower() not in ignored]
    return " ".join(word.capitalize() for word in words) or project_slug
