from __future__ import annotations

from company_ontology_agent.graph.models import Assertion, Entity
from company_ontology_agent.utils.ids import slugify
from company_ontology_agent.wiki.frontmatter import render_frontmatter


def entity_page(
    entity: Entity,
    project_slug: str,
    evidence: list[str],
    *,
    incoming: list[tuple[Assertion, Entity]],
    outgoing: list[tuple[Assertion, Entity]],
    evidence_snippets: dict[str, str],
) -> str:
    frontmatter = render_frontmatter(
        {
            "id": entity.id,
            "type": entity.type.value,
            "project": project_slug,
            "graph_node_id": entity.id,
            "sources": evidence,
        }
    )
    aliases = "\n".join(f"- {alias}" for alias in entity.aliases) or "- None"
    outgoing_lines = _relationship_lines(outgoing, "outgoing")
    incoming_lines = _relationship_lines(incoming, "incoming")
    evidence_lines = _evidence_lines(evidence, evidence_snippets)
    return (
        frontmatter
        + f"# {entity.type.value}: {entity.name}\n\n"
        + "## Summary\n\n"
        + f"{entity.name} is tracked as a {entity.type.value} in the project graph. "
        + f"It has {len(outgoing)} outgoing and {len(incoming)} incoming "
        + "validated relationships.\n\n"
        + "## Aliases\n\n"
        + f"{aliases}\n\n"
        + "## Outgoing Relationships\n\n"
        + f"{outgoing_lines}\n\n"
        + "## Incoming Relationships\n\n"
        + f"{incoming_lines}\n\n"
        + "## Evidence\n\n"
        + f"{evidence_lines}\n"
    )


def entity_filename(entity: Entity) -> str:
    return f"{slugify(entity.name)}.md"


def source_filename(source_path: str) -> str:
    return f"{slugify(source_path)}.md"


def _relationship_lines(items: list[tuple[Assertion, Entity]], direction: str) -> str:
    if not items:
        return "- None"
    lines = []
    for assertion, entity in sorted(items, key=lambda item: (item[0].predicate, item[1].name)):
        target = f"[[{entity_filename(entity).removesuffix('.md')}|{entity.name}]]"
        if direction == "outgoing":
            lines.append(
                f"- `{assertion.predicate}` -> {target} "
                f"(confidence {assertion.confidence:.2f}, {assertion.status.value})"
            )
        else:
            lines.append(
                f"- {target} -> `{assertion.predicate}` "
                f"(confidence {assertion.confidence:.2f}, {assertion.status.value})"
            )
    return "\n".join(lines)


def _evidence_lines(evidence: list[str], snippets: dict[str, str]) -> str:
    if not evidence:
        return "- None"
    lines = []
    for span_id in evidence:
        snippet = snippets.get(span_id, "").replace("\n", " ").strip()
        if len(snippet) > 240:
            snippet = snippet[:237] + "..."
        lines.append(f"- `{span_id}`: {snippet or 'No snippet available'}")
    return "\n".join(lines)
