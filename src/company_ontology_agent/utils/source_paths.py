from __future__ import annotations


def source_reference(value: str) -> tuple[str, str | None]:
    """Split a source artifact path from an optional record locator fragment."""
    artifact_path, separator, locator = value.partition("#")
    return artifact_path, locator if separator and locator else None


def artifact_path(value: str | None) -> str:
    return source_reference(value or "")[0]
