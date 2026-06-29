# OpenAI Extraction

V1 includes an OpenAI provider behind the `LLMProvider` protocol.

OpenAI extraction is optional. If the project uses:

```yaml
llm:
  provider: local
```

the deterministic local extractor is used.

To enable OpenAI:

```yaml
llm:
  provider: openai
```

and set:

```bash
OPENAI_API_KEY=...
ONTOLOGY_AGENT_LLM_MODEL=...
```

## Structured Outputs

The provider requests schema-adherent JSON matching the internal Pydantic extraction schema. Raw model text is not written to Neo4j.

The flow is:

```text
normalized text
  -> OpenAI structured output
  -> Pydantic validation
  -> ontology validation
  -> entity resolution
  -> graph repository
```

## Failure Behavior

If `llm.provider=openai` and either `OPENAI_API_KEY` or `ONTOLOGY_AGENT_LLM_MODEL` is missing, graph build fails clearly.

If you want no external LLM calls, keep `llm.provider=local`.
