from __future__ import annotations

from pathlib import Path


def validate_shacl(data_path: Path, shapes_path: Path) -> tuple[bool, str]:
    if not data_path.exists() or not shapes_path.exists():
        return True, "SHACL validation skipped; data or shapes file is absent."
    try:
        from pyshacl import validate
    except ImportError:  # pragma: no cover
        return False, "pySHACL is not installed."
    conforms, _, report = validate(str(data_path), shacl_graph=str(shapes_path))
    return bool(conforms), str(report)
