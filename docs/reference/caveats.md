# Caveats & Limitations

Known limitations of the current asset, with pointers to where they live. None are bugs — they
are deliberate scope/lightweight trade-offs.

## Retrieval / GraphRAG

- **Semantic search is off by default.** The retrievers (`retrieval/*.py`) are keyword +
  graph-traversal only. `embedding.provider` in `project.yaml` is **declarative** — no vectors
  are computed or stored until the embedding+vector-index path is implemented. See
  [GraphRAG Readiness](../architecture/graph-rag.md) for how to enable it.

## Progressive updates

- **`graphify update` refreshes code/AST cheaply (no LLM); changed *documents* are not
  semantically re-extracted by the incremental path** — use `run --full` after large doc changes.
- **Renames appear as a removal + an addition** on the Changes tab, because an entity's id is a
  hash of its normalized name + type. True rename detection (fuzzy matching) is out of scope.
- **The diff baseline is the dry-run/JSON path** (`data/processed/graph.prev.json`). Neo4j uses
  its own `stale`/`seen_at` marking and is not diffed here.
- **Community/cohesion deltas need a prior Graphify dated snapshot**; if none exists, that section
  is empty but the entity/assertion diff still works.

## Portal

- **Offline (`file://`): the "Load full graph" lazy-load is disabled** — browsers block local
  `fetch`. The inlined all-entity search index and wiki links cover offline use; full
  interactivity needs `ontology-agent portal serve`.
- **Page size scales with the ranking caps.** The data page inlines a ranked subset plus a
  search index over *every* entity, so it can reach a few MB on large corpora. Tune
  `REPO_LIMIT` / `DATA_LIMIT` / `DATA_PER_TYPE_CAP` in `portal/ranking.py` to trade
  comprehensiveness for size.
- **Raised wiki caps grow the wiki.** `WIKI_PER_TYPE_CAP` controls how many structured entities
  per type get a page; higher = more pages.

## Data model

- **Structured connectors emit one entity per row.** The underlying graph keeps every row (so
  `graph.json` and Neo4j are complete); the portal prunes for display and the wiki emits pages
  only for page-worthy entities. This is intentional — no row data is lost, only display is
  bounded.
