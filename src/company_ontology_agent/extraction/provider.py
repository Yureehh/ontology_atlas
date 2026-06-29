from __future__ import annotations

from typing import Protocol

from company_ontology_agent.extraction.schemas import StructuredExtractionPayload


class LLMProvider(Protocol):
    def extract(self, text: str) -> StructuredExtractionPayload:
        ...
