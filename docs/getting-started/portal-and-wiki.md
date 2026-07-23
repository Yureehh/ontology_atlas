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
Insights and Changes remain useful offline.

## Live cited answers

```bash
ontology-agent run --neo4j
ontology-agent rag index
ontology-agent portal build --neo4j
ontology-agent portal serve --port 8765
```

Open `http://127.0.0.1:8765/portal/index.html`.

The navigation is **Ask, Explore, Insights, Changes**. Explore is a single graph with
All, Architecture, and Business data filters.

Structured connector facts are authoritative. Graphify/OpenAI claims retain evidence text,
source path, confidence, and extractor. Ask carries those distinctions into citations and
refuses when retrieval finds no support.

`graph.html`, `GRAPH_TREE.html`, and `GRAPH_REPORT.md` appear only as secondary Explore
diagnostics. The raw Graphify map contains code and documents only; it is not the fused canonical
graph and contains no structured business data.

## Evaluation

Customize the generated `rag/questions.yaml`, then run:

```bash
ontology-agent rag evaluate
ontology-agent portal build --neo4j
```

The command reports citation validity, expected retrieval, refusal accuracy, latency, and
case-level failures, and saves the result to `rag/evaluation.json`.

## Wiki contents

The exporter writes architecture, data model, deployment, GraphRAG, module, API, entity, and
source pages. Entity pages expose incoming/outgoing relationships and evidence; source pages
preserve provenance. Commit useful `wiki/**/*.md` output for review. Treat `portal/` and saved
index/evaluation status as rebuildable demo artifacts.
