# Portal Architecture

The portal is the manager-facing surface over the curated graph. It is produced by
`PortalBuilder.build()` (`portal/builder.py`) and is **dependency-free** and
**offline-openable** — every page is a single self-contained HTML file with inlined CSS,
JS, and data (no external requests).

## Pages — one renderer, swapped data

`build()` emits four sibling pages that share the **same** renderer (`portal/assets/portal.js`)
and differ only by the JSON injected into a `<script type="application/json" id="portal-data">`
block, plus the full `graph.json`:

| File | Page | What it shows |
|------|------|---------------|
| `index.html` | `data` | the structured connector graph (default landing page) |
| `repo.html` | `repo` | the code/architecture ontology graph |
| `intelligence.html` | `intelligence` | Graphify intelligence dashboard (see [Graph Intelligence](graph-intelligence.md)) |
| `changes.html` | `changes` | run-to-run diff (see [Progressive Updates](../getting-started/progressive-updates.md)) |
| `graph.json` | — | the **complete** graph for download / lazy-load |

The renderer branches on `bootstrap.page`. The template lives in `portal/assets/`
(`shell.html`, `portal.css`, `portal.js`) and is shipped as package data, loaded via
`importlib.resources` and string-substituted at build time — so the 4 pages are byte-identical
except for their payload. To change the look, edit the assets, not Python.

## Ranking — plot the relevant, search everything

Each graph page inlines only a **bounded, ranked subset** of nodes so the HTML stays small,
while a compact `search_index` of **every** entity in the layer is also inlined so search is
omnicomprehensive even though the plot is not. Ranking lives in `portal/ranking.py` and reuses
the wiki's `PREDICATE_WEIGHTS`/`TYPE_WEIGHTS` so importance is defined once:

- `prune_layer()` scores nodes by weighted degree + type priority, always keeps the endpoints
  of curated key relationships (`key_relationship_endpoint_ids`), and caps each mapped type
  (`DATA_PER_TYPE_CAP`) so one high-cardinality type can't crowd out the rest.
- Tunable caps: `REPO_LIMIT` (500), `DATA_LIMIT` (600), `DATA_PER_TYPE_CAP` (120). Raising them
  shows more at the cost of page size; lowering them shrinks the page.
- `page_worthy_entity_ids()` decides which entities get a wiki page (all repo entities + the top
  `WIKI_PER_TYPE_CAP` structured entities per type). The portal's plotted set is always a subset,
  so **every plotted node has a wiki page** — no broken links.

## Client features (all dependency-free)

- **Search across all entities** — the box queries the inlined `search_index`, not just the
  plot. A hit that isn't plotted links to its wiki page or, when the portal is served, pulls
  the full graph in and focuses it.
- **Lazy-load full graph** — "Load full graph" fetches `graph.json` and merges it into the
  view (served only; under `file://` browsers block local fetch, so search + wiki links cover
  the offline case).
- **Deterministic clustered layout** — nodes are grouped by community/type, placed on a
  golden-angle phyllotaxis spiral, then normalised to fit the viewport. O(n), stable, no physics.
- **Impact analysis** — "What depends on this" runs a reverse BFS (depth 2) over the loaded
  links right in the browser.
- **SVG / PNG export**, **node permalinks** (`index.html#node=<id>`), zoom/pan, and a
  collapsible detail panel that deep-links to the wiki.

## Building

```bash
ontology-agent portal build --dry-run     # from a project's .ontology-agent/ dir
ontology-agent portal serve --port 8765   # then open /portal/index.html
```
