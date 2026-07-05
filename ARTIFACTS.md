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
| `graphify-out/graph.html` | graphify (only if `no_viz=false`) | **nobody** — see flag |
| `data/processed/graph.json` | build-graph (`--dry-run`) | wiki + portal (`repository.read_graph`), Changes-tab diff baseline |
| `data/processed/rejected/summary.md` | build-graph validation | **user** (rejected items) |
| Neo4j graph | build-graph (`--neo4j`) | Neo4j Browser / Cypher (`graph/explore.cypher`) |
| `wiki/**` (`index`, `architecture`, `entities/*`, …; `.md`+`.html`) | `WikiExporter.export` | **user** + portal node→wiki links |
| `portal/index.html` | `PortalBuilder.build` | **user** — redirect to the populated layer |
| `portal/{data-graph,repo,intelligence,changes}.html` | `PortalBuilder.build` | **user** (served, interactive graph) |
| `portal/graph.json` | `PortalBuilder.build` | portal "Load full graph" / download |

## Flags (generated but not consumed)
- **`graphify-out/graph.html`** — the standalone vis-network graph (physics simulation, freezes
  browsers on large graphs). The portal no longer links it and it's excluded from shareable bundles,
  so when `no_viz=false` it's pure dead weight. `ponytail:` set `graphify.no_viz: true` per project
  (portaledatareply already does) or flip the `GraphifyConfig.no_viz` default to stop generating it.
- **`data/normalized/*.jsonl`** — consumed only by the local structured-extraction fallback
  (`config.extraction.local_fallback_enabled`). With graphify as the sole extractor it's produced but
  unused; harmless (cheap, and useful for debugging ingestion).

## The shareable deliverable
A served tree of **`portal/` + `wiki/` + `graphify-out/`** (siblings), opened at **`/portal/`**.
`index.html` forwards to the populated graph; nodes link to `../wiki/*`; sidebar links to
`../graphify-out/{GRAPH_TREE.html,GRAPH_REPORT.md}`. `graph.html`, `.env`, and `data/` are excluded.
