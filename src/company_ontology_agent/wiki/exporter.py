from __future__ import annotations

import html
import re
from pathlib import Path

from markdown_it import MarkdownIt

from company_ontology_agent.graph.models import Assertion, Entity, EntityType, ExtractedGraph
from company_ontology_agent.portal.ranking import page_worthy_entity_ids
from company_ontology_agent.utils.display import public_project_name
from company_ontology_agent.utils.ids import slugify
from company_ontology_agent.wiki.relationships import key_relationship_sections
from company_ontology_agent.wiki.templates import (
    TYPE_DIRS,
    entity_filename,
    entity_page,
    entity_wiki_ref,
    source_filename,
)

TYPE_HEADINGS = {
    EntityType.decision: "Decisions",
    EntityType.requirement: "Requirements",
    EntityType.issue: "Issues",
    EntityType.task: "Tasks",
    EntityType.technology: "Technologies",
}

type EntityRelationshipIndex = dict[str, list[tuple[Assertion, Entity]]]


class WikiExporter:
    def export(
        self, graph: ExtractedGraph, output_path: Path, *, display_name: str | None = None
    ) -> list[Path]:
        output_path.mkdir(parents=True, exist_ok=True)
        title = public_project_name(graph.project_slug, display_name)
        self._clear_generated_markdown(output_path)
        for directory in [
            "entities",
            "decisions",
            "requirements",
            "issues",
            "tasks",
            "meetings",
            "modules",
            "apis",
            "sources",
            "domains",
            "datasets",
        ]:
            (output_path / directory).mkdir(parents=True, exist_ok=True)

        written: list[Path] = []
        evidence_by_entity = self._evidence_by_entity(graph)
        entities_by_id = {entity.id: entity for entity in graph.entities}
        spans_by_id = {span.id: span for span in graph.source_spans}
        incoming, outgoing = self._relationships_by_entity(graph, entities_by_id)
        evidence_snippets = {span.id: span.text for span in graph.source_spans}
        # Only emit a page per "page-worthy" entity (all code entities plus the top
        # structured entities per type). This keeps the wiki from exploding into one
        # page per data row while every node the portal renders still has a page.
        page_ids = page_worthy_entity_ids(graph)

        def _linked(items: list[tuple[Assertion, Entity]]) -> list[tuple[Assertion, Entity]]:
            return [item for item in items if item[1].id in page_ids]

        for entity in graph.entities:
            if entity.id not in page_ids:
                continue
            directory = TYPE_DIRS.get(entity.type, "entities")
            page = output_path / directory / entity_filename(entity)
            page.write_text(
                entity_page(
                    entity,
                    graph.project_slug,
                    evidence_by_entity.get(entity.id, []),
                    incoming=_linked(incoming.get(entity.id, [])),
                    outgoing=_linked(outgoing.get(entity.id, [])),
                    evidence_snippets=evidence_snippets,
                ),
                encoding="utf-8",
            )
            written.append(page)

        for source in graph.sources:
            source_page = output_path / "sources" / source_filename(source.path)
            source_assertions = [
                assertion
                for assertion in graph.assertions
                if spans_by_id.get(assertion.evidence_span_id)
                and spans_by_id[assertion.evidence_span_id].source_id == source.id
            ]
            source_page.write_text(
                self._source_page(source.title, source.path, source_assertions, entities_by_id),
                encoding="utf-8",
            )
            written.append(source_page)

        synthesized_pages = {
            "architecture.md": self._architecture_page(
                graph, incoming, outgoing, entities_by_id, title
            ),
            "data-model.md": self._typed_page(
                graph,
                "Data Model",
                {EntityType.data_model, EntityType.database, EntityType.data_store},
                title,
            ),
            "deployment.md": self._typed_page(
                graph,
                "Deployment",
                {
                    EntityType.deployment_unit,
                    EntityType.environment,
                    EntityType.config,
                    EntityType.secret_ref,
                },
                title,
            ),
            "data-graph.md": self._data_graph_page(graph, title),
            "graph-rag.md": self._graph_rag_page(graph, title),
            "manager-demo.md": self._manager_demo_page(graph, title),
        }
        for filename, content in synthesized_pages.items():
            page = output_path / filename
            page.write_text(content, encoding="utf-8")
            written.append(page)

        for module in [entity for entity in graph.entities if entity.type == EntityType.module]:
            page = output_path / "modules" / entity_filename(module)
            page.write_text(
                self._module_page(module, incoming.get(module.id, []), outgoing.get(module.id, [])),
                encoding="utf-8",
            )
            written.append(page)

        for api in [entity for entity in graph.entities if entity.type == EntityType.api_endpoint]:
            page = output_path / "apis" / entity_filename(api)
            page.write_text(
                self._module_page(api, incoming.get(api.id, []), outgoing.get(api.id, [])),
                encoding="utf-8",
            )
            written.append(page)

        for domain in self._domains(graph):
            page = output_path / "domains" / f"{slugify(domain)}.md"
            page.write_text(self._domain_page(graph, domain), encoding="utf-8")
            written.append(page)

        for dataset in self._datasets(graph):
            page = output_path / "datasets" / f"{slugify(dataset)}.md"
            page.write_text(self._dataset_page(graph, dataset), encoding="utf-8")
            written.append(page)

        summary = output_path / "graph-summary.md"
        summary.write_text(self._graph_summary(graph, title), encoding="utf-8")
        written.append(summary)

        index_lines = [
            f"# {title} Wiki",
            "",
            "This wiki is generated from validated graph state. "
            "Treat Neo4j and graph snapshots as canonical truth.",
            "",
            "## Overview",
            "",
            f"- Sources: {len(graph.sources)}",
            f"- Entities: {len(graph.entities)}",
            f"- Assertions: {len(graph.assertions)}",
            "- [[graph-summary|Graph summary]]",
            "- [[architecture|Architecture]]",
            "- [[data-model|Data model]]",
            "- [[deployment|Deployment]]",
            "- [[data-graph|Data graph]]",
            "- [[graph-rag|GraphRAG readiness]]",
            "- [[manager-demo|Manager demo guide]]",
            "",
            "## Key Pages",
            "",
        ]
        domains = self._domains(graph)
        if domains:
            index_lines.extend(["", "## Domains", ""])
            for domain in domains:
                index_lines.append(f"- [[domains/{slugify(domain)}|{domain}]]")
        for entity_type in [
            EntityType.decision,
            EntityType.requirement,
            EntityType.issue,
            EntityType.task,
            EntityType.technology,
        ]:
            items = [entity for entity in graph.entities if entity.type == entity_type][:25]
            if not items:
                continue
            index_lines.extend(["", f"### {TYPE_HEADINGS.get(entity_type, entity_type.value)}", ""])
            for entity in sorted(items, key=lambda item: item.name):
                directory = TYPE_DIRS.get(entity.type, "entities")
                index_lines.append(f"- [[{directory}/{slugify(entity.name)}|{entity.name}]]")
        index_lines.extend(["", "## Important Entities", ""])
        important = [entity for entity in graph.entities if entity.id in page_ids]
        for entity in sorted(important, key=lambda item: (item.type.value, item.name))[:80]:
            directory = TYPE_DIRS.get(entity.type, "entities")
            index_lines.append(f"- [[{directory}/{slugify(entity.name)}|{entity.name}]]")
        index = output_path / "index.md"
        index.write_text("\n".join(index_lines) + "\n", encoding="utf-8")
        written.append(index)
        written.extend(self._render_html_pages(output_path, title))
        return written

    def _clear_generated_markdown(self, output_path: Path) -> None:
        for filename in ["index.md", "index.html", "graph-summary.md", "graph-summary.html"]:
            path = output_path / filename
            if path.exists():
                path.unlink()
        for directory in [
            "entities",
            "decisions",
            "requirements",
            "issues",
            "tasks",
            "meetings",
            "modules",
            "apis",
            "sources",
            "domains",
            "datasets",
        ]:
            folder = output_path / directory
            if not folder.exists():
                continue
            for path in [*folder.glob("*.md"), *folder.glob("*.html")]:
                path.unlink()

    def _render_html_pages(self, output_path: Path, display_name: str) -> list[Path]:
        written: list[Path] = []
        for markdown_path in sorted(output_path.rglob("*.md")):
            html_path = markdown_path.with_suffix(".html")
            relative_root = _relative_root(markdown_path.parent, output_path)
            html_path.write_text(
                _markdown_page_to_html(
                    markdown_path.read_text(encoding="utf-8"),
                    relative_root,
                    display_name,
                ),
                encoding="utf-8",
            )
            written.append(html_path)
        return written

    def _evidence_by_entity(self, graph: ExtractedGraph) -> dict[str, list[str]]:
        evidence: dict[str, list[str]] = {}
        for assertion in graph.assertions:
            evidence.setdefault(assertion.subject_id, []).append(assertion.evidence_span_id)
            evidence.setdefault(assertion.object_id, []).append(assertion.evidence_span_id)
        for entity in graph.entities:
            evidence.setdefault(entity.id, []).extend(entity.source_span_ids)
        return {key: sorted(set(values)) for key, values in evidence.items()}

    def _relationships_by_entity(
        self, graph: ExtractedGraph, entities_by_id: dict[str, Entity]
    ) -> tuple[EntityRelationshipIndex, EntityRelationshipIndex]:
        incoming: dict[str, list[tuple[Assertion, Entity]]] = {}
        outgoing: dict[str, list[tuple[Assertion, Entity]]] = {}
        for assertion in graph.assertions:
            subject = entities_by_id.get(assertion.subject_id)
            object_ = entities_by_id.get(assertion.object_id)
            if subject is None or object_ is None:
                continue
            outgoing.setdefault(subject.id, []).append((assertion, object_))
            incoming.setdefault(object_.id, []).append((assertion, subject))
        return incoming, outgoing

    def _graph_summary(self, graph: ExtractedGraph, display_name: str) -> str:
        type_counts: dict[str, int] = {}
        predicate_counts: dict[str, int] = {}
        for entity in graph.entities:
            type_counts[entity.type.value] = type_counts.get(entity.type.value, 0) + 1
        for assertion in graph.assertions:
            predicate_counts[assertion.predicate] = predicate_counts.get(assertion.predicate, 0) + 1
        lines = [
            f"# {display_name} Graph Summary",
            "",
            "## Counts",
            "",
            f"- Sources: {len(graph.sources)}",
            f"- Source spans: {len(graph.source_spans)}",
            f"- Chunks: {len(graph.chunks)}",
            f"- Entities: {len(graph.entities)}",
            f"- Assertions: {len(graph.assertions)}",
            "",
            "## Entities By Type",
            "",
        ]
        lines.extend(
            f"- {name}: {count}"
            for name, count in sorted(type_counts.items(), key=lambda item: (-item[1], item[0]))
        )
        lines.extend(["", "## Assertions By Predicate", ""])
        lines.extend(
            f"- `{name}`: {count}"
            for name, count in sorted(
                predicate_counts.items(), key=lambda item: (-item[1], item[0])
            )
        )
        return "\n".join(lines) + "\n"

    def _architecture_page(
        self,
        graph: ExtractedGraph,
        incoming: EntityRelationshipIndex,
        outgoing: EntityRelationshipIndex,
        entities_by_id: dict[str, Entity],
        display_name: str,
    ) -> str:
        modules = [
            entity
            for entity in graph.entities
            if entity.type == EntityType.module or entity.metadata.get("mapped_type") == "Module"
        ]
        technologies = [entity for entity in graph.entities if entity.type == EntityType.technology]
        lines = [
            f"# {display_name} Architecture",
            "",
            (
                "This page is generated from Graphify/OpenAI extraction, structured "
                "dataset mappings, and validated graph state."
            ),
            "",
            "## Architecture Modules",
            "",
        ]
        for module in sorted(modules, key=lambda item: item.name):
            lines.append(f"- [[modules/{slugify(module.name)}|{module.name}]]")
        lines.extend(["", "## Technology Stack", ""])
        for technology in sorted(technologies, key=lambda item: item.name):
            lines.append(f"- [[{entity_wiki_ref(technology)}|{technology.name}]]")
        lines.extend(
            [
                "",
                "## Key Relationships",
                "",
                "Key relationships are ranked by graph centrality, predicate importance, "
                "evidence, source diversity, and domain coverage.",
                "",
            ]
        )
        sections = key_relationship_sections(graph)
        for section, items in sections.items():
            if not items:
                continue
            lines.extend(["", f"### {section}", ""])
            for assertion, subject, object_ in items:
                lines.append(
                    f"- **{subject.name}** `{assertion.predicate}` **{object_.name}** "
                    f"({assertion.confidence:.2f})"
                )
        return "\n".join(lines) + "\n"

    def _typed_page(
        self,
        graph: ExtractedGraph,
        title: str,
        entity_types: set[EntityType],
        display_name: str,
    ) -> str:
        items = [entity for entity in graph.entities if entity.type in entity_types]
        lines = [f"# {display_name} {title}", "", "Generated from validated graph state.", ""]
        if not items:
            lines.append("No dedicated nodes were detected for this section.")
        for item in sorted(items, key=lambda entity: entity.name):
            lines.append(f"- [[{entity_wiki_ref(item)}|{item.name}]]")
        return "\n".join(lines) + "\n"

    def _graph_rag_page(self, graph: ExtractedGraph, display_name: str) -> str:
        return (
            f"# {display_name} GraphRAG\n\n"
            "Ask cited questions across:\n\n"
            "- curated architecture relationships,\n"
            "- Graphify-derived code/documentation relationships,\n"
            "- source-backed assertions with evidence spans,\n"
            "- module, API, data, deployment, and technology nodes.\n\n"
            "Suggested first questions:\n\n"
            "- What are the main backend/frontend/data responsibilities?\n"
            "- Which technologies support deployment and persistence?\n"
            "- Which files define API endpoints and data models?\n"
            "\nRun `ontology-agent rag index`, then use Ask or `ontology-agent rag ask`.\n"
        )

    def _data_graph_page(self, graph: ExtractedGraph, display_name: str) -> str:
        by_dataset: dict[str, list[Entity]] = {}
        for entity in graph.entities:
            dataset = str(entity.metadata.get("dataset") or "")
            if dataset:
                by_dataset.setdefault(dataset, []).append(entity)
        lines = [
            f"# {display_name} Data Graph",
            "",
            "This page summarizes structured dataset entities projected into the graph.",
            "",
        ]
        if not by_dataset:
            lines.append("No structured datasets are configured for this project.")
            return "\n".join(lines) + "\n"
        for dataset, entities in sorted(by_dataset.items()):
            type_counts: dict[str, int] = {}
            for entity in entities:
                mapped_type = str(entity.metadata.get("mapped_type", entity.type.value))
                type_counts[mapped_type] = type_counts.get(mapped_type, 0) + 1
            lines.extend(["", f"## {dataset}", ""])
            for mapped_type, count in sorted(
                type_counts.items(), key=lambda item: (-item[1], item[0])
            ):
                lines.append(f"- {mapped_type}: {count}")
        return "\n".join(lines) + "\n"

    def _manager_demo_page(self, graph: ExtractedGraph, display_name: str) -> str:
        return (
            f"# {display_name} Manager Demo Guide\n\n"
            "Demo flow:\n\n"
            "1. Open Ask and run the Customer Profile impact question.\n"
            "2. Expand its citations and explain authoritative versus extracted evidence.\n"
            "3. Open Explore and switch between Architecture and Business data layers.\n"
            "4. Show Trust for source coverage, index freshness, and evaluation results.\n"
            "5. Use `GRAPH_TREE.html` only as secondary extraction diagnostics.\n\n"
            f"Current graph: {len(graph.entities)} entities, {len(graph.assertions)} assertions.\n"
        )

    def _module_page(
        self,
        entity: Entity,
        incoming: list[tuple[Assertion, Entity]],
        outgoing: list[tuple[Assertion, Entity]],
    ) -> str:
        lines = [f"# {entity.name}", "", f"Type: `{entity.type.value}`", ""]
        if entity.description:
            lines.extend([entity.description, ""])
        lines.extend(["## Outgoing", ""])
        if not outgoing:
            lines.append("- None")
        for assertion, target in sorted(
            outgoing, key=lambda item: (item[0].predicate, item[1].name)
        ):
            lines.append(f"- `{assertion.predicate}` [[{entity_wiki_ref(target)}|{target.name}]]")
        lines.extend(["", "## Incoming", ""])
        if not incoming:
            lines.append("- None")
        for assertion, source in sorted(
            incoming, key=lambda item: (item[0].predicate, item[1].name)
        ):
            lines.append(f"- [[{entity_wiki_ref(source)}|{source.name}]] `{assertion.predicate}`")
        return "\n".join(lines) + "\n"

    def _source_page(
        self,
        title: str,
        path: str,
        assertions: list[Assertion],
        entities_by_id: dict[str, Entity],
    ) -> str:
        lines = [f"# Source: {title}", "", f"Path: `{path}`", "", "## Assertions", ""]
        if not assertions:
            lines.append("- None")
        for assertion in sorted(assertions, key=lambda item: item.predicate):
            subject = entities_by_id.get(assertion.subject_id)
            object_ = entities_by_id.get(assertion.object_id)
            if subject is None or object_ is None:
                continue
            lines.append(
                f"- {subject.name} `{assertion.predicate}` {object_.name} "
                f"(confidence {assertion.confidence:.2f})"
            )
        return "\n".join(lines) + "\n"

    def _domains(self, graph: ExtractedGraph) -> list[str]:
        domains = {
            str(entity.metadata.get("domain"))
            for entity in graph.entities
            if entity.metadata.get("domain")
        }
        return sorted(domains)

    def _datasets(self, graph: ExtractedGraph) -> list[str]:
        datasets = {
            str(entity.metadata.get("dataset"))
            for entity in graph.entities
            if entity.metadata.get("dataset")
        }
        return sorted(datasets)

    def _domain_page(self, graph: ExtractedGraph, domain: str) -> str:
        entities = [entity for entity in graph.entities if entity.metadata.get("domain") == domain]
        datasets = sorted(
            {
                str(entity.metadata.get("dataset"))
                for entity in entities
                if entity.metadata.get("dataset")
            }
        )
        lines = [f"# Domain: {domain}", "", f"- Entities: {len(entities)}", ""]
        if datasets:
            lines.extend(["## Datasets", ""])
            for dataset in datasets:
                lines.append(f"- [[../datasets/{slugify(dataset)}|{dataset}]]")
        lines.extend(["", "## Entities", ""])
        for entity in sorted(entities, key=lambda item: item.name)[:200]:
            mapped_type = entity.metadata.get("mapped_type", entity.type.value)
            lines.append(f"- [[{entity_wiki_ref(entity)}|{entity.name}]] (`{mapped_type}`)")
        return "\n".join(lines) + "\n"

    def _dataset_page(self, graph: ExtractedGraph, dataset: str) -> str:
        entities = [
            entity for entity in graph.entities if entity.metadata.get("dataset") == dataset
        ]
        domain = entities[0].metadata.get("domain") if entities else ""
        connector = entities[0].metadata.get("connector") if entities else ""
        lines = [
            f"# Dataset: {dataset}",
            "",
            f"- Domain: {domain}",
            f"- Connector: {connector}",
            f"- Entities: {len(entities)}",
            "",
            "## Entities",
            "",
        ]
        for entity in sorted(entities, key=lambda item: item.name)[:200]:
            mapped_type = entity.metadata.get("mapped_type", entity.type.value)
            lines.append(f"- [[{entity_wiki_ref(entity)}|{entity.name}]] (`{mapped_type}`)")
        return "\n".join(lines) + "\n"


def _relative_root(page_dir: Path, output_path: Path) -> str:
    depth = len(page_dir.relative_to(output_path).parts)
    return "./" if depth == 0 else "../" * depth


def _markdown_page_to_html(markdown: str, relative_root: str, display_name: str) -> str:
    body = _markdown_body_to_html(_strip_frontmatter(markdown), relative_root)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(display_name)} Wiki</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #060b14;
      --panel: #0e1726;
      --panel-2: #172235;
      --line: #31415c;
      --text: #e5e7eb;
      --muted: #94a3b8;
      --accent: #67e8f9;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background:
        radial-gradient(circle at 80% 0%, rgba(34, 211, 238, .12), transparent 28%),
        var(--bg);
      color: var(--text);
      font: 16px/1.6 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
    }}
    main {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 40px 28px 78px;
    }}
    nav {{
      margin-bottom: 24px;
      color: var(--muted);
      font-size: 14px;
    }}
    h1, h2, h3 {{ line-height: 1.2; }}
    h1 {{ font-size: 42px; margin: 0 0 18px; letter-spacing: 0; }}
    h2 {{ margin-top: 36px; border-bottom: 1px solid var(--line); padding-bottom: 8px; }}
    h3 {{ margin-top: 28px; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    code {{
      background: #020617;
      border: 1px solid #1e293b;
      border-radius: 5px;
      padding: 1px 5px;
      color: #bae6fd;
    }}
    pre {{
      overflow-x: auto;
      background: #020617;
      border: 1px solid #1e293b;
      border-radius: 8px;
      padding: 14px;
    }}
    ul, ol {{
      padding-left: 24px;
      background: rgba(14, 23, 38, .52);
      border: 1px solid rgba(49, 65, 92, .7);
      border-radius: 8px;
      padding-top: 10px;
      padding-bottom: 10px;
    }}
    li {{ margin: 6px 0; }}
    p, li {{ max-width: 92ch; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
    th, td {{ border: 1px solid var(--line); padding: 8px 10px; text-align: left; }}
    th {{ background: var(--panel-2); }}
    blockquote {{
      margin: 18px 0;
      border-left: 3px solid var(--accent);
      padding-left: 14px;
      color: #cbd5e1;
    }}
  </style>
</head>
<body>
<main>
<nav><a href="{relative_root}index.html">{html.escape(display_name)} Wiki</a></nav>
{body}
</main>
</body>
</html>
"""


def _strip_frontmatter(markdown: str) -> str:
    if markdown.startswith("---\n"):
        _, _, remainder = markdown.partition("\n---\n")
        return remainder.lstrip()
    return markdown


def _markdown_body_to_html(markdown: str, relative_root: str) -> str:
    prepared = re.sub(
        r"\[\[([^|\]]+)(?:\|([^\]]+))?\]\]",
        lambda match: _wiki_link_markdown(match, relative_root),
        markdown,
    )
    return str(MarkdownIt("commonmark", {"html": False}).render(prepared))


def _wiki_link_markdown(match: re.Match[str], relative_root: str) -> str:
    target = match.group(1).strip()
    label = match.group(2).strip() if match.group(2) else target
    href = f"{relative_root}{target}.html"
    safe_label = label.replace("[", "(").replace("]", ")")
    return f"[{safe_label}]({href})"
