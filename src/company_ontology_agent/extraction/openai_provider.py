from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from pydantic import TypeAdapter

from company_ontology_agent.extraction.provider import LLMProvider
from company_ontology_agent.extraction.schemas import StructuredExtractionPayload
from company_ontology_agent.ontology.mappings import VALID_PREDICATES


@dataclass(frozen=True)
class OpenAIProviderConfig:
    api_key: str
    model: str


class OpenAIProvider(LLMProvider):
    def __init__(self, config: OpenAIProviderConfig) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("OpenAI extraction requires the openai package.") from exc
        self.client = OpenAI(api_key=config.api_key)
        self.model = config.model
        self._adapter = TypeAdapter(StructuredExtractionPayload)

    def extract(self, text: str) -> StructuredExtractionPayload:
        schema = openai_strict_json_schema(self._adapter.json_schema())
        response = self.client.responses.create(
            model=self.model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Extract a project ontology graph from the user text. "
                        "Return only entities and assertions grounded in explicit evidence. "
                        "Use concise names, allowed entity types, clear predicates, "
                        "and confidence. "
                        "Prefer these predicates exactly: "
                        f"{', '.join(sorted(VALID_PREDICATES))}."
                    ),
                },
                {"role": "user", "content": text},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "structured_extraction_payload",
                    "schema": schema,
                    "strict": True,
                }
            },
        )
        output_text = getattr(response, "output_text", None)
        if not output_text:
            output_text = _extract_text_from_response(response)
        return StructuredExtractionPayload.model_validate_json(output_text)


def _extract_text_from_response(response: object) -> str:
    data = response.model_dump() if hasattr(response, "model_dump") else response
    if isinstance(data, dict):
        for output in data.get("output", []):
            for content in output.get("content", []):
                text = content.get("text")
                if isinstance(text, str):
                    return text
    return json.dumps(data)


def openai_strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    strict_schema = cast(dict[str, Any], json.loads(json.dumps(schema)))
    _normalize_schema_node(strict_schema)
    return strict_schema


def _normalize_schema_node(node: object) -> None:
    if isinstance(node, list):
        for item in node:
            _normalize_schema_node(item)
        return

    if not isinstance(node, dict):
        return

    node.pop("default", None)

    properties = node.get("properties")
    if isinstance(properties, dict):
        node["additionalProperties"] = False
        node["required"] = list(properties)
        for child in properties.values():
            _normalize_schema_node(child)

    for key in ("$defs", "definitions"):
        definitions = node.get(key)
        if isinstance(definitions, dict):
            for child in definitions.values():
                _normalize_schema_node(child)

    for key in ("items", "anyOf", "allOf", "oneOf"):
        _normalize_schema_node(node.get(key))
