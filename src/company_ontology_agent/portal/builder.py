"""Generate the manager-facing ontology portal.

The portal is three sibling HTML pages that share one renderer (``assets/portal.js``)
and differ only by the JSON payload injected into each:

* ``index.html``        — the structured **data** graph (default landing page)
* ``repo.html``         — the **repo/code** ontology graph
* ``intelligence.html`` — a Graphify graph-intelligence dashboard

The complete graph is always written to ``graph.json`` for download/serving; each page
only inlines a bounded, pre-ranked subset (see :mod:`portal.ranking`) so the HTML stays
small and opens offline via ``file://``.
"""

from __future__ import annotations

import json
import re
from importlib.resources import files
from pathlib import Path

from company_ontology_agent.extraction.graphify_adapter import (
    load_graphify_analysis,
    load_previous_analysis,
)
from company_ontology_agent.graph.diffing import diff_graphs
from company_ontology_agent.graph.models import (
    Assertion,
    Entity,
    EntityType,
    ExtractedGraph,
    assertion_graph_kind,
    entity_graph_kind,
)
from company_ontology_agent.graph.repository import JsonGraphRepository
from company_ontology_agent.portal import changes as changes_mod
from company_ontology_agent.portal import intelligence as intel
from company_ontology_agent.portal import ranking
from company_ontology_agent.utils.display import public_project_name
from company_ontology_agent.utils.ids import slugify
from company_ontology_agent.wiki.relationships import key_relationship_ids

JsonDict = dict[str, object]

_ASSETS = files("company_ontology_agent.portal") / "assets"
_STALE_FILES = ["repo-ontology.html"]

# (filename, page id, graph layer). ``index.html`` is generated separately as a redirect to
# whichever layer actually has content, so a fresh portal always opens on a populated graph.
_PAGES = [
    ("data-graph.html", "data", "data"),
    ("repo.html", "repo", "repo"),
    ("intelligence.html", "intelligence", None),
    ("changes.html", "changes", None),
]


def _asset(name: str) -> str:
    return (_ASSETS / name).read_text(encoding="utf-8")


class PortalBuilder:
    def build(
        self,
        graph: ExtractedGraph,
        project_root: Path,
        output_path: Path,
        *,
        display_name: str | None = None,
    ) -> list[Path]:
        output_path.mkdir(parents=True, exist_ok=True)
        for stale in _STALE_FILES:
            (output_path / stale).unlink(missing_ok=True)

        title = public_project_name(graph.project_slug, display_name)
        page_ids = ranking.page_worthy_entity_ids(graph)
        nodes, links = self._graph_data(graph, page_ids)
        full_graph = {"nodes": nodes, "links": links}
        (output_path / "graph.json").write_text(json.dumps(full_graph, indent=2), encoding="utf-8")

        graphify_out = project_root / "graphify-out"
        analysis = load_graphify_analysis(graphify_out)
        report_exists = (graphify_out / "GRAPH_REPORT.md").exists()
        intelligence = intel.build_intelligence(
            graph, analysis, page_ids=page_ids, report_exists=report_exists
        )
        artifacts = self._graphify_artifacts(graphify_out)

        # Run-to-run diff for the Changes tab (dry-run/JSON baseline only).
        previous = JsonGraphRepository(
            project_root / "data" / "processed" / "graph.json"
        ).read_previous(graph.project_slug)
        diff = diff_graphs(previous, graph, load_previous_analysis(graphify_out), analysis)
        name_by_id = {entity.id: entity.name for entity in graph.entities}
        if previous is not None:
            name_by_id.update({entity.id: entity.name for entity in previous.entities})
        changes = changes_mod.shape_changes(diff, page_ids, name_by_id)

        shell = _asset("shell.html")
        css = _asset("portal.css")
        script = _asset("portal.js")
        pinned = ranking.key_relationship_endpoint_ids(graph)

        written: list[Path] = []
        for filename, page, layer in _PAGES:
            bootstrap = self._bootstrap(
                graph, nodes, links, page=page, layer=layer,
                title=title, intelligence=intelligence, changes=changes, pinned=pinned,
            )
            bootstrap["artifacts"] = artifacts
            html = (
                shell.replace("__TITLE__", _esc(f"{title} · Ontology Portal"))
                .replace("__SUBTITLE__", _esc(_SUBTITLES[page]))
                .replace("__NAV__", self._nav(page))
                .replace("__CSS__", css)
                .replace("__BOOTSTRAP_JSON__", _json_for_script(bootstrap))
                .replace("__JS__", script)
            )
            path = output_path / filename
            path.write_text(html, encoding="utf-8")
            written.append(path)

        # Land on whichever layer actually has content — repo for code/knowledge projects,
        # data for structured-connector projects. The empty layer stays reachable via its tab.
        repo_count = sum(1 for node in nodes if node["graph_kind"] == "repo")
        data_count = sum(1 for node in nodes if node["graph_kind"] == "data")
        landing = "repo.html" if repo_count >= data_count else "data-graph.html"
        (output_path / "index.html").write_text(
            _redirect_page(f"{title} · Ontology Portal", landing), encoding="utf-8"
        )
        written.append(output_path / "index.html")

        written.append(output_path / "graph.json")
        return written

    # ------------------------------------------------------------------ data
    def _graph_data(
        self, graph: ExtractedGraph, page_ids: set[str]
    ) -> tuple[list[JsonDict], list[JsonDict]]:
        nodes: list[JsonDict] = []
        node_kind: dict[str, str] = {}
        for entity in graph.entities:
            kind = entity_graph_kind(entity)
            node_kind[entity.id] = kind
            mapped_type = str(entity.metadata.get("mapped_type") or entity.type.value)
            nodes.append(
                {
                    "id": entity.id,
                    "name": entity.name,
                    "type": entity.type.value,
                    "mapped_type": mapped_type,
                    "visual_type": _visual_type(entity, kind, mapped_type),
                    "community": entity.community,
                    "domain": str(entity.metadata.get("domain") or ""),
                    "dataset": str(entity.metadata.get("dataset") or ""),
                    "connector": str(entity.metadata.get("connector") or ""),
                    "source_path": entity.source_path,
                    "description": entity.description,
                    "graph_kind": kind,
                    "extraction_source": entity.extraction_source,
                    "confidence_tier": entity.confidence_tier,
                    "wiki": self._wiki_link(entity, page_ids),
                }
            )

        node_id_set = {node["id"] for node in nodes}
        key_ids = key_relationship_ids(graph)
        links: list[JsonDict] = []
        for assertion in graph.assertions:
            if assertion.subject_id not in node_id_set or assertion.object_id not in node_id_set:
                continue
            links.append(
                {
                    "id": assertion.id,
                    "source": assertion.subject_id,
                    "target": assertion.object_id,
                    "predicate": assertion.predicate,
                    "confidence": assertion.confidence,
                    "extractor": assertion.extractor,
                    "evidence": assertion.evidence_text,
                    "source_path": assertion.source_path,
                    "graph_kind": assertion_graph_kind(assertion, node_kind),
                    "dataset": str(assertion.metadata.get("dataset") or ""),
                    "extraction_source": assertion.extraction_source,
                    "confidence_tier": assertion.confidence_tier,
                    "evidence_level": _evidence_level(assertion),
                    "key_relationship": assertion.id in key_ids,
                }
            )
        return nodes, links

    def _bootstrap(
        self,
        graph: ExtractedGraph,
        nodes: list[JsonDict],
        links: list[JsonDict],
        *,
        page: str,
        layer: str | None,
        title: str,
        intelligence: JsonDict | None,
        changes: JsonDict,
        pinned: frozenset[str],
    ) -> JsonDict:
        stats: JsonDict = {
            "entities": len(graph.entities),
            "assertions": len(graph.assertions),
            "sources": len(graph.sources),
        }
        if page == "intelligence":
            summary = intelligence.get("summary") if intelligence else None
            if isinstance(summary, dict):
                stats["communities"] = summary.get("community_count", 0)
            return {"page": page, "title": title, "stats": stats, "intelligence": intelligence}
        if page == "changes":
            return {"page": page, "title": title, "stats": stats, "changes": changes}

        layer_nodes = [n for n in nodes if n["graph_kind"] == layer]
        layer_links = [link for link in links if link["graph_kind"] == layer]
        limit = ranking.DATA_LIMIT if layer == "data" else ranking.REPO_LIMIT
        per_type_cap = ranking.DATA_PER_TYPE_CAP if layer == "data" else None
        shown_nodes, shown_links = ranking.prune_layer(
            layer_nodes,
            layer_links,
            limit=limit,
            per_type_cap=per_type_cap,
            pinned_ids=pinned,
            link_limit=ranking.LINK_LIMIT,
        )
        stats.update(
            {
                "shown_nodes": len(shown_nodes),
                "total_nodes": len(layer_nodes),
                "shown_links": len(shown_links),
                "total_links": len(layer_links),
            }
        )
        return {
            "page": page,
            "kind": layer,
            "title": title,
            "nodes": shown_nodes,
            "links": shown_links,
            "search_index": _search_index(layer_nodes),
            "stats": stats,
            "full_graph_url": "graph.json",
        }

    # --------------------------------------------------------------- helpers
    def _graphify_artifacts(self, graphify_out: Path) -> list[JsonDict]:
        # graph.html is graphify's full physics render — the "cool" one, but heavy on
        # low-memory machines. It's only emitted when no_viz is false, so it's linked
        # only when present; the portal's own Repo-graph tab stays the light everyday view.
        candidates = [
            ("graph.html", "Interactive graph"),
            ("GRAPH_TREE.html", "Repository tree"),
            ("GRAPH_REPORT.md", "Full report"),
        ]
        return [
            {"label": label, "url": f"../graphify-out/{name}"}
            for name, label in candidates
            if (graphify_out / name).exists()
        ]

    def _wiki_link(self, entity: Entity, page_ids: set[str]) -> str | None:
        if entity.id in page_ids:
            return f"../wiki/entities/{slugify(entity.name)}.html"
        dataset = entity.metadata.get("dataset")
        if dataset:
            return f"../wiki/datasets/{slugify(str(dataset))}.html"
        return None

    def _nav(self, active: str) -> str:
        tabs = [("data", "data-graph.html", "Data graph"),
                ("repo", "repo.html", "Repo graph"),
                ("intelligence", "intelligence.html", "Intelligence"),
                ("changes", "changes.html", "Changes")]
        parts = []
        for page, href, label in tabs:
            cls = ' class="active"' if page == active else ""
            parts.append(f'<a href="{href}"{cls}>{label}</a>')
        return "".join(parts)


def _search_index(layer_nodes: list[JsonDict]) -> list[JsonDict]:
    """Compact index of *every* entity in a layer so search covers nodes the plot omits.

    Kept deliberately small (id/name/type/wiki) so full-corpus search works offline without
    bloating the page; ``wiki`` is retained so a non-plotted hit can still open its page.
    """
    return [
        {
            "i": node["id"],
            "n": node["name"],
            "t": node.get("visual_type") or node.get("mapped_type") or node.get("type"),
            "w": node.get("wiki"),
        }
        for node in layer_nodes
    ]


_SUBTITLES = {
    "data": "Structured-data entities and their relationships extracted from connected sources.",
    "repo": "Evidence-first code & architecture ontology extracted from the repository.",
    "intelligence": "Graphify graph intelligence — hotspots, surprising links and community cohesion.",
    "changes": "What changed since the previous run — added, removed and modified graph elements.",
}


def _redirect_page(title: str, target: str) -> str:
    """Tiny landing page that forwards to the populated graph layer."""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{_esc(title)}</title>"
        f'<meta http-equiv="refresh" content="0; url={target}">'
        f"<script>location.replace({json.dumps(target)})</script></head>"
        '<body style="font-family:system-ui,sans-serif;background:#0b1220;color:#cbd5e1;padding:2rem">'
        f'Opening the ontology portal… <a style="color:#7dd3fc" href="{target}">open the graph</a> '
        "if it doesn’t load automatically.</body></html>"
    )


def _json_for_script(payload: JsonDict) -> str:
    # Safe to embed inside <script type="application/json">; only </ needs neutralising.
    return json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")


def _esc(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _evidence_level(assertion: Assertion) -> str:
    if assertion.extraction_source == "structured_connector":
        return "authoritative"
    if assertion.evidence_text or assertion.source_path or assertion.graphify_id:
        return "evidence_backed"
    return "weak"


def _visual_type(entity: Entity, graph_kind: str, mapped_type: str) -> str:
    if graph_kind == "data":
        return mapped_type
    return entity.type.value if entity.type != EntityType.concept else _concept_visual_type(entity)


def _concept_visual_type(entity: Entity) -> str:
    label = entity.name.strip()
    source_path = (entity.source_path or "").lower()
    if re.search(r"^(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s+/", label):
        return EntityType.api_endpoint.value
    if label.endswith("()"):
        return EntityType.function.value
    if re.search(r"\.(py|js|jsx|ts|tsx|java|go|rs|sql|ya?ml|toml|md)$", label.lower()):
        return EntityType.file.value
    if source_path.endswith((".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs")):
        if re.match(r"^[A-Z][A-Za-z0-9_]+$", label):
            return EntityType.class_.value
        if re.match(r"^[_a-zA-Z][\w_]*\(\)$", label):
            return EntityType.function.value
    return entity.type.value
