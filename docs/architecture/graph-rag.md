# GraphRAG Readiness

V1 does not claim to be a hosted vector platform. It prepares the graph and evidence
shape needed for GraphRAG.

## Retrieval Shape

The graph contains:

- curated ontology entities such as `Module`, `APIEndpoint`, `DataModel`, `Technology`,
  `Database`, and `DeploymentUnit`,
- validated assertions with predicate, confidence, status, extractor, and evidence,
- source spans and chunks for provenance,
- direct Neo4j relationships for graph traversal,
- raw Graphify nodes/edges as supporting extraction context when available.

## Query Path

The query path is:

```text
question
  -> graph entity match
  -> relationship neighborhood
  -> evidence spans/wiki chunks
  -> answer with trace id
```

The retrieval layer lives in `retrieval/` (`graph_retriever`, `wiki_retriever`,
`hybrid_retriever`, `answerer`) and is consumed in-process — it grounds answers on the same
`graph.json` and wiki the portal renders.

## Retrieval artifacts for downstream RAG

The two outputs are RAG-ready as-is:

- **`portal/graph.json`** — the complete graph: every node (`id`, `name`, `type`, `community`,
  `source_path`, `description`) and every edge (`predicate`, `confidence`, `evidence`,
  `source_path`, `evidence_level`, `key_relationship`). Use it for graph grounding / traversal.
- **`wiki/**.md`** — markdown with YAML frontmatter (`id`, `type`, `graph_node_id`, `sources`)
  and `[[wikilinks]]`, ideal for chunk-level retrieval with provenance.

## Embeddings (semantic search) — off by default

!!! warning "Declarative only today"
    `embedding.provider: none` in `project.yaml` is **declarative**. No embeddings are computed
    or stored, and the retrievers do keyword + graph-traversal matching only — there is no vector
    search yet. Setting `provider: openai` alone changes nothing until the vector path is built.

To enable semantic retrieval later you would: (1) compute embeddings for wiki chunks / entities
with the configured provider, (2) populate a vector index (Neo4j `chunk_embeddings` or a local
store), and (3) extend `graph_retriever`/`wiki_retriever` to query it. Kept out of the default
build to stay lightweight, dependency-light, and zero-cost. See [Caveats](../reference/caveats.md).
