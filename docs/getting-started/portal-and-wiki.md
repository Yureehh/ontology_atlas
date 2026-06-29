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

The portal is three sibling pages that share a single renderer and differ only by the
graph data injected into each:

- `portal/index.html`: the default landing page — the structured connector data graph,
- `portal/repo.html`: the normalized repo/code ontology graph,
- `portal/intelligence.html`: a Graphify dashboard of architecture hotspots, surprising
  connections, and community cohesion,
- `portal/graph.json`: the complete graph for download (each page inlines only a bounded,
  ranked subset so the HTML stays small and opens offline),
- links to `wiki/index.md`, `wiki/architecture.md`, `wiki/data-graph.md`, and
  `wiki/graph-rag.md`,
- links to Graphify `graph.html`, `GRAPH_TREE.html`, and `GRAPH_REPORT.md` when present.

The portal graph is not the same artifact as Graphify's native `graph.html` or
`GRAPH_TREE.html`. Graphify's files are the primary visual for repository/code
exploration. The portal is the product/demo surface around those artifacts and the
primary visual for structured connector data.

The generated visual roles are:

- `graphify-out/graph.html`: canonical repo/code visual graph.
- `graphify-out/GRAPH_TREE.html`: canonical repo/code hierarchy.
- `portal/index.html`: structured connector graph view (default).
- `portal/repo.html`: normalized ontology view used by Neo4j, wiki, and retrieval.

The main portal entrypoint is `portal/index.html`, and it opens directly on the
structured-data graph. `repo.html` and `intelligence.html` load the same renderer with
different data, so the views cannot drift into different layouts. Use the data graph when
you want a Graphify-like graph surface for connector data that Graphify itself does not
read. The normalized repo ontology view is secondary and should not be presented as
better than Graphify's native repo graph.

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
