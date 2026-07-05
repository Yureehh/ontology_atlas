# Portal And Wiki

The generated project has two human-facing outputs:

- `wiki/`: reviewable markdown knowledge base.
- `portal/`: local static demo surface for graph, wiki, and Graphify artifacts.

Both are generated from graph state. Do not manually treat either one as canonical truth.

## Build

From a generated project:

```bash
make check
```

This builds the local dry-run graph, wiki, and portal without Neo4j. Build only the
portal from the dry-run graph with:

```bash
make portal
ontology-agent portal build --dry-run
```

Serve it locally:

```bash
make view
ontology-agent portal serve --port 8765
```

Then open:

```text
http://localhost:8765/portal/index.html
```

## Portal Contents

The portal is generated pages that share one renderer, differing only by the graph data
injected into each:

- `portal/index.html`: a lightweight redirect that opens whichever layer has content —
  the repo graph for code/knowledge projects, the data graph for structured-connector ones,
- `portal/repo.html`: the repo/code ontology graph,
- `portal/data-graph.html`: the structured-connector data graph,
- `portal/intelligence.html`: a Graphify dashboard (hotspots, surprising links, community cohesion),
- `portal/changes.html`: what changed since the previous run,
- `portal/graph.json`: the complete graph for download (each page inlines only a bounded,
  ranked subset so the HTML stays small and opens offline),
- sidebar links to `GRAPH_TREE.html` and `GRAPH_REPORT.md` (Graphify's own artifacts).

The portal deliberately does **not** embed or link Graphify's standalone `graph.html`: that
file runs a physics simulation that freezes on large graphs. It remains a separate Graphify
artifact — a pretty standalone view for small graphs, opened on its own. The portal's graph uses
a static layout (no physics), a ranked node cap, and full-corpus search, so it scales.

This prevents large business datasets from hiding the repository architecture. The
portal keeps the complete graph in `portal/graph.json`, but each layer initially shows
only a ranked subset. Use `Show all`, search, domain/dataset filters, relationship
filters, or double-click a node to expand its neighborhood.

The portal does not present semantic extraction as certain truth. Structured connector
relationships are labelled as authoritative, while Graphify/OpenAI relationships expose
their confidence tier, evidence text, source path, and extractor. Dashed relationships
indicate inferred semantic edges that should be reviewed against the cited source.

Neo4j is not required for this path. If Neo4j is unavailable or its Explore view is
showing only provenance dots, use the portal and Graphify artifacts for the visual demo.

## Wiki Contents

The wiki is not a flat entity dump. The V1 exporter writes:

- `index.md`: entrypoint and top graph sections,
- `architecture.md`: backend/frontend/data/deployment view,
- `data-model.md`: models, databases, and stores,
- `deployment.md`: deployment/config/environment nodes,
- `graph-rag.md`: retrieval and reasoning readiness,
- `manager-demo.md`: suggested demo flow,
- `modules/*.md`: module/community pages,
- `apis/*.md`: endpoint pages,
- `entities/*.md`: entity pages with incoming/outgoing relationships and evidence,
- `sources/*.md`: provenance pages.

## Commit Policy

Commit `wiki/**/*.md` when the output is useful for review. Treat `portal/` as rebuildable
unless a specific demo snapshot needs to be preserved.
