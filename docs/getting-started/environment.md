# Environment

Generated projects use `.env.example` as the template for local secrets and runtime settings.

Copy it before running a real V1 pipeline:

```bash
cp .env.example .env
```

## Required For OpenAI Extraction

```bash
OPENAI_API_KEY=...
ONTOLOGY_AGENT_LLM_MODEL=...
```

`ONTOLOGY_AGENT_LLM_MODEL` is intentionally env-only. The asset does not hardcode a default model because model availability and company policy can change.

## Required For Neo4j Desktop

```bash
NEO4J_URI=bolt://localhost:7687
NEO4J_DATABASE=neo4j
NEO4J_USER=neo4j
NEO4J_PASSWORD=...
```

These values override `project.yaml` at runtime. Secrets must stay in `.env` or the shell environment and must not be committed.

## Required For GraphRAG

```bash
ONTOLOGY_AGENT_EMBEDDING_MODEL=...
```

The embedding model's output size must match `embedding.dimension` in `project.yaml`.
Graph construction does not require embeddings, but `rag index` and live Ask do. GraphRAG
also uses `OPENAI_API_KEY` and `ONTOLOGY_AGENT_LLM_MODEL` for answer generation.
