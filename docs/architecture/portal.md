# Portal Architecture

The portal is an answer-first surface over one canonical graph. `PortalBuilder.build()` emits
self-contained pages with shared CSS and JavaScript plus a complete `graph.json` payload.

## Pages

| File | Purpose |
|---|---|
| `index.html` | redirect to Ask |
| `ask.html` | live cited answers, evidence, and impact paths |
| `explore.html` | one graph with All, Architecture, and Business data filters |
| `intelligence.html` | architecture hotspots and graph insights |
| `changes.html` | run-to-run graph diff |
| `graph.json` | complete graph for lazy loading and export |

Legacy graph redirects are removed. Atlas turns Graphify output into a bounded community story map
at `graph.html`; the dense original is retained at `graph.raw.html`. Both are secondary code/document
diagnostics, never the fused business graph.

## Static and live behavior

Explore is offline-capable: its ranked graph subset, visible-node search index, CSS, and JavaScript are
inlined. Under `file://`, Ask explains that live answers require the local server. Running
`ontology-agent portal serve` mounts the project read-only and adds the GraphRAG status and query
endpoints. The server binds to `127.0.0.1` unless explicitly overridden.

## Ranking and layers

Architecture begins with at most 30 package/system/source-root aggregates in a directional,
left-to-right card layout. Selecting an aggregate loads the full canonical payload and drills into
its modules, classes, and functions. Business data keeps its clustered concept-first layout.
Relationship and dataset facets are recomputed from the current layer, search, and drill scope.

Ranking lives in `portal/ranking.py` and reuses the wiki's predicate/type weights. Current caps
are `ARCHITECTURE_LIMIT=30`, `DATA_LIMIT=360`, and `DATA_PER_TYPE_CAP=100`.

## Client features

- full-corpus search and wiki links,
- Architecture and Business data views over one graph,
- dynamic relationship/dataset facets with URL-persisted scope,
- Architecture breadcrumbs, drill-down, direction arrows, and search-to-focus,
- deterministic non-physics layout,
- reverse two-hop impact analysis,
- evidence, confidence, and source details,
- SVG/PNG export, zoom, pan, and node permalinks,
- Ask readiness, citations, evidence tiers, retrieval scores, and relationship paths.

## Build and serve

```bash
ontology-agent portal build --neo4j
ontology-agent portal serve --port 8765
```

Open `http://127.0.0.1:8765/portal/index.html`.
