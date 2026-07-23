"""Generate a bounded, conversational map from Graphify's code/document graph."""

from __future__ import annotations

import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from company_ontology_agent.graph.models import Entity, ExtractedGraph

_MAX_COMMUNITIES = 40
_MAX_MEMBERS = 60
_MARKER = 'data-ontology-atlas-code-map="true"'


def write_code_map(graph: ExtractedGraph, output_path: Path) -> Path:
    """Preserve Graphify's raw HTML and replace the primary map with a curated view."""
    output_path.mkdir(parents=True, exist_ok=True)
    target = output_path / "graph.html"
    raw_target = output_path / "graph.raw.html"
    if target.exists() and not raw_target.exists():
        existing = target.read_text(encoding="utf-8", errors="replace")
        if _MARKER not in existing:
            raw_target.write_text(existing, encoding="utf-8")
    target.write_text(_render(graph), encoding="utf-8")
    return target


def _render(graph: ExtractedGraph) -> str:
    entities = {entity.id: entity for entity in graph.entities}
    grouped: dict[str, list[Entity]] = defaultdict(list)
    for entity in graph.entities:
        grouped[entity.community or _fallback_group(entity)].append(entity)

    cross_counts: Counter[str] = Counter()
    connections: Counter[tuple[str, str]] = Counter()
    for assertion in graph.assertions:
        source = entities.get(assertion.subject_id)
        target = entities.get(assertion.object_id)
        if source is None or target is None:
            continue
        source_group = source.community or _fallback_group(source)
        target_group = target.community or _fallback_group(target)
        if source_group == target_group:
            continue
        cross_counts[source_group] += 1
        cross_counts[target_group] += 1
        connections[(source_group, target_group)] += 1

    chosen = sorted(
        grouped,
        key=lambda group: (-(len(grouped[group]) + cross_counts[group] * 2), group.casefold()),
    )[:_MAX_COMMUNITIES]
    keys = {group: f"community-{index}" for index, group in enumerate(chosen)}
    cards = []
    details = []
    for group in chosen:
        members = sorted(
            grouped[group],
            key=lambda entity: (-_member_degree(entity.id, graph), entity.name.casefold()),
        )[:_MAX_MEMBERS]
        title = _short_title(group)
        description = _description(members)
        cards.append(
            '<button class="community-card" '
            f'data-community="{html.escape(keys[group])}">'
            f"<strong>{html.escape(title)}</strong>"
            f"<span>{html.escape(description)}</span>"
            f"<small>{len(grouped[group]):,} components · "
            f"{cross_counts[group]:,} external links</small>"
            "</button>"
        )
        member_items = "".join(
            "<li><strong>"
            f"{html.escape(_short_component(entity.name))}</strong>"
            f"<span>{html.escape(entity.type.value)}"
            + (f" · {html.escape(entity.source_path)}" if entity.source_path else "")
            + "</span></li>"
            for entity in members
        )
        related = sorted(
            (
                (target if source == group else source, count)
                for (source, target), count in connections.items()
                if group in {source, target} and (target if source == group else source) in keys
            ),
            key=lambda item: (-item[1], item[0]),
        )[:8]
        related_html = "".join(
            f"<span>{html.escape(_short_title(other))} · {count}</span>" for other, count in related
        ) or "<span>No cross-community dependency detected.</span>"
        details.append(
            f'<section id="{keys[group]}" class="community-detail" hidden>'
            '<button class="back">← All areas</button>'
            f"<h2>{html.escape(title)}</h2><p>{html.escape(description)}</p>"
            f'<div class="related">{related_html}</div><ul>{member_items}</ul></section>'
        )

    payload = json.dumps({"shown": len(chosen), "total": len(grouped)})
    return f"""<!doctype html>
<html lang="en" {_MARKER}>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Code &amp; docs map</title>
<style>
:root{{--bg:#07101c;--card:#0e1b2d;--line:#263a55;--text:#e5edf8;--muted:#93a4bc;--accent:#38bdf8}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 Inter,system-ui,sans-serif}}
main{{max-width:1180px;margin:auto;padding:42px 24px 70px}}
h1{{font-size:clamp(32px,5vw,58px);margin:.2rem 0}}
.lead{{color:var(--muted);max-width:720px;font-size:18px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin-top:28px}}
.community-card{{min-height:150px;text-align:left;background:var(--card);
border:1px solid var(--line);
border-radius:16px;padding:18px;color:inherit;cursor:pointer}}
.community-card:hover{{border-color:var(--accent);transform:translateY(-2px)}}
.community-card strong{{display:block;font-size:18px;margin-bottom:8px}}
.community-card span,.community-card small{{display:block;color:var(--muted)}}
.community-card small{{margin-top:18px}}
.community-detail{{max-width:860px}}
.back{{background:none;border:0;color:var(--accent);padding:0;cursor:pointer;font:inherit}}
.related{{display:flex;gap:8px;flex-wrap:wrap;margin:20px 0}}
.related span{{border:1px solid var(--line);border-radius:999px;
padding:5px 10px;color:var(--muted)}}
ul{{list-style:none;padding:0;display:grid;
grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:8px}}
li{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:11px}}
li strong,li span{{display:block;overflow-wrap:anywhere}}
li span{{color:var(--muted);font-size:12px;margin-top:3px}}
</style></head><body><main><header id="overview">
<div>ONTOLOGY ATLAS</div><h1>Code &amp; docs map</h1>
<p class="lead">A concise view of how this repository is organized and which areas depend on
each other. This map contains code and documents only—not business records.</p>
<div class="grid">{''.join(cards)}</div></header>{''.join(details)}</main>
<script>"use strict";const META={payload};
document.querySelectorAll('.community-card').forEach(card=>card.addEventListener('click',()=>{{
document.getElementById('overview').hidden=true;
document.getElementById(card.dataset.community).hidden=false;scrollTo(0,0)}}));
document.querySelectorAll('.back').forEach(button=>button.addEventListener('click',()=>{{
button.closest('section').hidden=true;
document.getElementById('overview').hidden=false;scrollTo(0,0)}}));</script>
</body></html>"""


def _fallback_group(entity: Entity) -> str:
    path = (entity.source_path or "").strip("/")
    parts = [part for part in path.split("/") if part]
    return "/".join(parts[:2]) if parts else entity.type.value


def _short_title(value: str) -> str:
    cleaned = re.sub(r"\b(community|package|module|component)\b", " ", value, flags=re.I)
    cleaned = re.sub(r"[_/.-]+", " ", cleaned)
    words = cleaned.split()
    return " ".join(words[:4]).title()[:34] or "Repository Area"


def _short_component(value: str) -> str:
    leaf = value.rsplit("/", 1)[-1]
    return leaf[:42] + ("…" if len(leaf) > 42 else "")


def _description(members: list[Entity]) -> str:
    types = Counter(entity.type.value for entity in members)
    dominant = ", ".join(name.lower() for name, _ in types.most_common(2))
    paths = [Path(entity.source_path).parts[0] for entity in members if entity.source_path]
    location = Counter(paths).most_common(1)[0][0] if paths else "the repository"
    return f"Primarily {dominant or 'code and documentation'} from {location}."


def _member_degree(entity_id: str, graph: ExtractedGraph) -> int:
    return sum(
        assertion.subject_id == entity_id or assertion.object_id == entity_id
        for assertion in graph.assertions
    )
