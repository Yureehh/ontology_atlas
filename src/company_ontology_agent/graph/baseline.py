from __future__ import annotations

import hashlib
import json
from pathlib import Path

from company_ontology_agent.config.project_config import ProjectConfig

_PIPELINE_VERSION = "ontology-atlas-v3"


def scope_fingerprint(root: Path, config: ProjectConfig) -> dict[str, object]:
    """Describe the inputs that must stay stable for a meaningful run-to-run diff."""
    datasets = []
    for dataset in config.datasets:
        mapping_path = (root / dataset.mapping).resolve()
        mapping_hash = (
            hashlib.sha256(mapping_path.read_bytes()).hexdigest()
            if mapping_path.is_file()
            else "missing"
        )
        datasets.append(
            {
                **dataset.model_dump(mode="json"),
                "mapping_hash": mapping_hash,
            }
        )
    scope = {
        "pipeline_version": _PIPELINE_VERSION,
        "project_slug": config.project_slug,
        "graphify": {
            "enabled": config.graphify.enabled,
            "backend": config.graphify.backend,
            "mode": config.graphify.mode,
            "input_path": config.graphify.input_path,
        },
        "datasets": datasets,
        "extraction": config.extraction.model_dump(mode="json"),
    }
    digest = hashlib.sha256(
        json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {"digest": digest, "scope": scope}


def write_scope_fingerprint(root: Path, config: ProjectConfig) -> Path:
    path = root / "data" / "processed" / "scope-fingerprint.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scope_fingerprint(root, config), indent=2), encoding="utf-8")
    return path
