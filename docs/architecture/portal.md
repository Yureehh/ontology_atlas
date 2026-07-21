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
| `trust.html` | evidence, structural quality, freshness, and evaluation |
| `graph.json` | complete graph for lazy loading and export |

`repo.html` and `data-graph.html` are compatibility redirects to filtered Explore views. They
are not separate products. Graphify's `graph.html` is disabled and never linked. Its tree and
report remain in Trust under diagnostics.

## Static and live behavior

Explore is offline-capable: its ranked graph subset, full search index, CSS, and JavaScript are
inlined. Under `file://`, Ask explains that live answers require the local server. Running
`ontology-agent portal serve` mounts the project read-only and adds the GraphRAG status and query
endpoints. The server binds to `127.0.0.1` unless explicitly overridden.

## Ranking and layers

Architecture and Business data nodes are ranked separately, then combined in one renderer so a
high-cardinality dataset cannot hide the code architecture. The client-side layer selector
filters the same payload. Search covers every entity even when the initial plotted graph is
bounded; the full graph can be lazy-loaded when served.

Ranking lives in `portal/ranking.py` and reuses the wiki's predicate/type weights. Current caps
are `REPO_LIMIT=500`, `DATA_LIMIT=600`, and `DATA_PER_TYPE_CAP=120`.

## Client features

- full-corpus search and wiki links,
- All, Architecture, and Business data layers,
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
