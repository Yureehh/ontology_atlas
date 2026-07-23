# Graphify

V1 integrates the open-source Graphify package documented at [graphify.net](https://graphify.net/).

The package name is `graphifyy`; the CLI command is `graphify`.

## Install

Graphify is included in the package dependencies as `graphifyy[openai,neo4j,pdf]`.

If you install the agent with `uv tool install`, the public command is:

```bash
ontology-agent
```

The ontology agent resolves Graphify from its installed tool environment when running
`ontology-agent graphify ...`.

You can still install Graphify as a UV tool for direct terminal use, but it is not
required for the ontology agent:

```bash
uv tool install --force "graphifyy[openai,neo4j,pdf]"
```

## Command Shape

For V1 demo quality, Graphify is the primary extraction and graph-intelligence layer.
The deterministic local extractor remains available only as an offline safety fallback.

The agent runs Graphify against the raw corpus, not the normalized JSONL files.
For `graphifyy==0.8.38`, the command shape is:

```bash
graphify extract ./data/raw \
  --backend openai \
  --mode deep \
  --model "$ONTOLOGY_AGENT_LLM_MODEL" \
  --out .
```

After extraction, the agent can run Graphify community/report helpers:

```bash
ontology-agent graphify cluster
ontology-agent graphify tree
ontology-agent graphify query "What are the main backend modules?"
ontology-agent graphify explain "Backend"
ontology-agent graphify path "Frontend" "Database"
```

Graphify outputs remain intermediate artifacts under:

```text
graphify-out/
├── graph.json
├── graph.html
├── graph.raw.html
├── GRAPH_TREE.html
├── GRAPH_REPORT.md
├── cache/
└── cypher.txt
```

Atlas rewrites `graph.html` as a bounded 20–40-community Code & docs map and preserves Graphify's
dense original as `graph.raw.html`. Neither is the fused graph with business data. Set
`graphify.no_viz: true` for CI or very large runs; use Explore for the canonical product view.

## Canonical Graph Rule

Graphify is the source graph layer, not the final source of truth. The agent parses
`graphify-out/graph.json`, preserves Graphify nodes/edges as supporting evidence,
then creates a curated ontology projection with validated entities, assertions, and
Neo4j visual relationships.

Direct Graphify pushes to Neo4j stay disabled by default.

## Modes

Without an LLM key, Graphify can still extract local structural information for code-heavy corpora.

With `OPENAI_API_KEY` and `--backend openai`, Graphify can perform semantic extraction for docs, PDFs, and diagrams.

The agent configuration controls:

```yaml
graphify:
  enabled: true
  input_path: ./data/raw
  output_path: ./graphify-out
  backend: openai
  mode: deep
  update: true
  no_viz: false
  timeout_seconds: null
  auto_name_communities: true
```

Direct Graphify pushes to Neo4j stay disabled by default because the ontology agent
owns canonical provenance, validation, and idempotent writes.

Deep OpenAI extraction can take a long time on a real repository. By default,
`timeout_seconds: null` means Graphify is allowed to finish naturally while the agent
prints heartbeat logs. If you explicitly set an integer timeout, the agent terminates
the external process after that many seconds and continues from `graphify-out/graph.json`
when that artifact was already written.

`auto_name_communities` is enabled by default. The agent first uses Graphify's generated
community labels when available, then deterministically names unlabeled communities from
their actual node names, source paths, and entity types. This avoids manager-facing
labels like `Community 1` without requiring manual curation.

## Graphify-Only Test Path

Use this when you want to test the semantic source graph without Neo4j:

```bash
cd /path/to/repo/.ontology-agent
ontology-agent doctor
ontology-agent graphify run
ontology-agent graphify cluster
ontology-agent graphify tree
open graphify-out/graph.html
open graphify-out/graph.raw.html
open graphify-out/GRAPH_TREE.html
open graphify-out/GRAPH_REPORT.md
```

This validates Graphify extraction and reporting only. To build the curated ontology
projection, run `make check` for local dry-run output or `make refresh` for Neo4j.
