from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


class NormalizedRecord(BaseModel):
    id: str
    source_id: str
    source_path: str
    source_type: str
    title: str
    text: str
    ordinal: int = 0
    sha256: str


class Ingestor(Protocol):
    def ingest(self, path: Path, project_root: Path) -> list[Path]:
        ...
