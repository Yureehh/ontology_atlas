from __future__ import annotations

import re

from company_ontology_agent.utils.hashing import stable_hash


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "untitled"


def stable_id(prefix: str, *parts: object) -> str:
    raw = "::".join(str(part) for part in parts)
    return f"{prefix}_{stable_hash(raw)[:16]}"
