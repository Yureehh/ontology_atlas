# Graph Intelligence

The **Intelligence** portal page turns Graphify's analysis (and a few in-process metrics)
into a manager-readable dashboard. Shaping lives in `portal/intelligence.py::build_intelligence`,
which is pure (graph + analysis dict in, JSON out) and rendered by `renderIntelligence()` in
`portal/assets/portal.js`.

## Where the data comes from

Graphify writes `graphify-out/.graphify_analysis.json` during clustering with keys
`gods`, `surprises`, `communities`, `cohesion`, `tokens`. `load_graphify_analysis()`
(`extraction/graphify_adapter.py`) loads it. Everything below is derived from that file plus
the curated graph — **no extra LLM calls, no tokens**.

## The views

- **Architecture hotspots** — the highest-degree "god" nodes (`gods`), ranked with degree bars.
  Hubs worth reviewing for coupling. Each links to its wiki page (resolved via `graphify_id`).
- **Surprising connections** — links Graphify flagged as unexpected (`surprises`): cross-community
  bridges or cross-directory calls, with its `why` explanation and source-file chips.
- **Refactor candidates** — sizeable communities with the **lowest cohesion** (`cohesion`),
  i.e. loosely-knit clusters doing too many things. Sorted ascending by cohesion.
- **Suggested questions** — generated from structure (god nodes → "What depends on X?",
  surprises → "Why does A relate to B?", communities → "What is this community responsible for?")
  and **answered by traversing the graph in-process** (incoming edges, the surprise's own `why`,
  community members). Free, deterministic, no live service.
- **Data quality** — in-process structural checks over the relationships: duplicate edges
  (same subject-predicate-object), self-loops, and multi-edge pairs. A quick trust signal.
- **Community cohesion** — every community with its size and cohesion score.
- **Explore artifacts** — links to Graphify's own `GRAPH_TREE.html` and `GRAPH_REPORT.md`
  (`graph.html` is linked only as a raw code/document diagnostic when generated).

## Design note: in-process vs shelling out

Graphify also exposes free BFS commands (`query`, `explain`, `affected`, `diagnose`). We compute
the equivalent signals (impact, quality, question answers) **in-process from the same extracted
graph** rather than spawning dozens of subprocesses per build. It's faster, deterministic,
unit-testable, and keeps the package light — while still surfacing exactly what those commands
would tell you. If a graph is absent, every section degrades to an empty state.
