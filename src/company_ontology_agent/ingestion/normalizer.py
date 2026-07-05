from __future__ import annotations

import json
import logging
from pathlib import Path

from company_ontology_agent.ingestion.base import NormalizedRecord
from company_ontology_agent.ingestion.pdf import read_pdf
from company_ontology_agent.ingestion.transcript import read_transcript_json
from company_ontology_agent.utils.hashing import file_hash, stable_hash
from company_ontology_agent.utils.ids import stable_id

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".json"}


def normalize_file(path: Path, project_root: Path) -> NormalizedRecord | None:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        return None
    try:
        if suffix in {".txt", ".md"}:
            text = path.read_text(encoding="utf-8")
            source_type = "markdown" if suffix == ".md" else "text"
        elif suffix == ".pdf":
            text = read_pdf(path)
            source_type = "pdf"
        else:
            text = read_transcript_json(path)
            source_type = "transcript_json"
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        # Skip an unreadable/corrupt file rather than aborting the whole ingestion run.
        logger.warning("Skipping unreadable source file %s: %s", path, exc)
        return None

    relative = (
        path.resolve().relative_to(project_root.resolve())
        if path.is_relative_to(project_root)
        else path
    )
    sha = file_hash(path)
    source_id = stable_id("source", str(relative), sha)
    return NormalizedRecord(
        id=stable_id("record", source_id, stable_hash(text)),
        source_id=source_id,
        source_path=str(relative),
        source_type=source_type,
        title=path.stem.replace("-", " ").replace("_", " ").title(),
        text=text,
        sha256=sha,
    )


def write_jsonl(records: list[NormalizedRecord], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(record.model_dump_json() + "\n")
    return output_path


def read_normalized_jsonl(path: Path) -> list[NormalizedRecord]:
    records: list[NormalizedRecord] = []
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(NormalizedRecord.model_validate(json.loads(line)))
    return records
