# Progressive Updates & Diffs

The agent is built to be **re-run periodically**. After the first full extraction, later runs
refresh cheaply and the portal shows a **Changes** tab with exactly what moved since last time.

## Incremental by default

```bash
ontology-agent run --dry-run     # auto-detects a prior extraction and updates incrementally
ontology-agent run --full        # forces a full from-scratch re-extraction (LLM cost)
```

On `run`, the pipeline checks `prior_extraction_exists(graphify-out/)` (a `graph.json` + a
`cache/` dir). If present and `graphify.update` is enabled, it calls **`graphify update`**
(`GraphifyExtractor.incremental_update`) which re-extracts only changed code files using
Graphify's per-file cache — **no LLM tokens**. On the first run, or with `--full`, it does a
full `graphify extract`. `launch` and `run` use the incremental default.

!!! note "Code vs documents"
    `graphify update` refreshes **code/AST** cheaply. A semantic re-extraction of changed
    **documents** still needs `run --full`. Use `--full` after large doc changes; use the
    default for routine re-runs after code changes.

## How the diff works

Entity and assertion ids are deterministic SHA256 hashes (`utils/ids.stable_id`), so a node
keeps its id across runs unless its **name or type** changes. That makes a by-id diff reliable:

1. Before overwriting the canonical graph, `JsonGraphRepository.snapshot_previous()` copies
   `data/processed/graph.json` → `graph.prev.json` (the baseline).
2. At portal build, `graph/diffing.py::diff_graphs` compares the new graph against the baseline:
   entities **added / removed / modified** (a description/community/source-path change while the
   id is stable), relationships **added / removed**, and community **size / cohesion** deltas
   (using Graphify's dated `.graphify_analysis.json` snapshots).
3. `portal/changes.py` separates architecture, business-record, and relationship changes, then
   computes a bounded set of directly affected upstream/downstream areas for the **Changes** tab.

On the very first run there is no baseline, so the Changes tab shows a friendly empty state.
A **rename** shows up as a removal + an addition (because the id is name+type based) — this is
called out on the page.

## Test Changes with a real source edit

```bash
cd /path/to/project/.ontology-agent
ontology-agent launch
```

Then change one source file or structured-data artifact and run `ontology-agent launch` again.
Open `/portal/changes.html`: the page separates architecture changes, business-record movement,
relationship changes, and directly affected upstream/downstream areas. If the source scope,
mappings, row limits, or extraction settings changed, it refuses the comparison instead of
showing a misleading mass diff. A run with no knowledge changes shows an explicit zero-change
state.
