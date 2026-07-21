# Artifacts `ontology-agent` produces

Every file/dir the tool writes, where, and what consumes it.

| Path | Written by | Consumed by |
|------|-----------|-------------|
| `data/raw/**` | `init` (`import_raw_files`) | graphify extract (its input dir) |
| `data/normalized/*.jsonl` | `ingest` (`normalize_file`+`write_jsonl`) | local structured-extraction fallback (see flag) |
| `graphify-out/graph.json` | graphify extract | `parse_graphify_graph`, `cluster`/`tree` |
| `graphify-out/GRAPH_REPORT.md` | graphify | **user** + portal "Full report" link |
| `graphify-out/GRAPH_TREE.html` | graphify `tree` | **user** + portal "Repository tree" link |
| `graphify-out/manifest.json`, `.graphify_analysis.json`, `.graphify_labels.json` | graphify | `apply_community_names`, portal Intelligence tab (`load_graphify_analysis`) |
| `data/processed/graph.json` | build-graph (`--dry-run`) | wiki + portal (`repository.read_graph`), Changes-tab diff baseline |
| `data/processed/rejected/summary.md` | build-graph validation | **user** (rejected items) |
| Neo4j graph | build-graph (`--neo4j`) | Neo4j Browser / Cypher (`graph/explore.cypher`) |
| `wiki/**` (`index`, `architecture`, `entities/*`, …; `.md`+`.html`) | `WikiExporter.export` | **user** + portal node→wiki links |
| `rag/index-status.json` | `rag index` | Trust page (freshness and stale cleanup) |
| `rag/evaluation.json` | `rag evaluate` | Trust page (golden-question score) |
| `portal/index.html` | `PortalBuilder.build` | **user** — redirect to Ask |
| `portal/{ask,explore,intelligence,changes,trust}.html` | `PortalBuilder.build` | **user** (answer-first workspace) |
| `portal/graph.json` | `PortalBuilder.build` | portal "Load full graph" / download |

## Retired artifact

- **`graphify-out/graph.html`** — disabled by the default `graphify.no_viz: true`. It duplicated
  Explore and its physics simulation freezes on large graphs. It is not linked or shared.
- **`data/normalized/*.jsonl`** — consumed only by the local structured-extraction fallback
  (`config.extraction.local_fallback_enabled`). With graphify as the sole extractor it's produced but
  unused; harmless (cheap, and useful for debugging ingestion).

## The shareable deliverable
A served tree of **`portal/` + `wiki/` + `graphify-out/`** (siblings), opened at **`/portal/`**.
`index.html` forwards to Ask; nodes link to `../wiki/*`; Trust links to
`../graphify-out/{GRAPH_TREE.html,GRAPH_REPORT.md}`. `graph.html`, `.env`, and `data/` are excluded.
