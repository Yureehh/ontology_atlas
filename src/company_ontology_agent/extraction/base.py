from __future__ import annotations

from pathlib import Path
from typing import Protocol

from company_ontology_agent.graph.models import ExtractedGraph


class KGExtractor(Protocol):
    def extract(self, input_path: Path, project_slug: str) -> ExtractedGraph:
        ...
