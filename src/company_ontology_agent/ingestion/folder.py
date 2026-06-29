from __future__ import annotations

from pathlib import Path

from company_ontology_agent.ingestion.normalizer import (
    SUPPORTED_EXTENSIONS,
    normalize_file,
    write_jsonl,
)
from company_ontology_agent.utils.ids import stable_id


def ingest_folder(input_path: Path, project_root: Path) -> list[Path]:
    if not input_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")
    files = [input_path] if input_path.is_file() else sorted(input_path.rglob("*"))
    records = [
        record
        for file_path in files
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS
        for record in [normalize_file(file_path, project_root)]
        if record is not None
    ]
    output = (
        project_root
        / "data"
        / "normalized"
        / f"{stable_id('normalized', str(input_path))}.jsonl"
    )
    return [write_jsonl(records, output)] if records else []
