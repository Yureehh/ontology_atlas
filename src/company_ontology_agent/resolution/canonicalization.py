from __future__ import annotations

from company_ontology_agent.utils.ids import slugify


def canonical_name(value: str) -> str:
    return slugify(value).replace("-", " ")
