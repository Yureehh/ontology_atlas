# Portal and Wiki

The generated project has two human-facing outputs:

- `portal/`: the answer-first client demo.
- `wiki/`: reviewable markdown context and provenance.

Both are generated from canonical graph state; neither should be edited as source truth.

## Offline review

```bash
ontology-agent run --dry-run
ontology-agent portal build --dry-run
```

Open `portal/index.html`. Ask will explain that live answers are unavailable, while Explore,
Insights, Changes, and Trust remain useful offline.

## Live cited answers

```bash
ontology-agent run --neo4j
ontology-agent rag index
ontology-agent portal build --neo4j
ontology-agent portal serve --port 8765
```

Open `http://127.0.0.1:8765/portal/index.html`.

The navigation is **Ask, Explore, Insights, Changes, Trust**. Explore is a single graph with
All, Architecture, and Business data filters. The old `repo.html` and `data-graph.html` URLs
redirect to those filters for compatibility.

Structured connector facts are authoritative. Graphify/OpenAI claims retain evidence text,
source path, confidence, and extractor. Ask carries those distinctions into citations and
refuses when retrieval finds no support.

`GRAPH_TREE.html` and `GRAPH_REPORT.md` appear only under Trust diagnostics. Graphify's
standalone `graph.html` is disabled and is not part of the shareable output.

## Trust and evaluation

Customize the generated `rag/questions.yaml`, then run:

```bash
ontology-agent rag evaluate
ontology-agent portal build --neo4j
```

Trust will show graph quality, source coverage, rejected assertions, vector-index freshness,
stale cleanup counts, and the evaluation report.

## Wiki contents

The exporter writes architecture, data model, deployment, GraphRAG, module, API, entity, and
source pages. Entity pages expose incoming/outgoing relationships and evidence; source pages
preserve provenance. Commit useful `wiki/**/*.md` output for review. Treat `portal/` and saved
index/evaluation status as rebuildable demo artifacts.
