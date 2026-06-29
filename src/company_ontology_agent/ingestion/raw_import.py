from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

SourceProfile = Literal["all", "code-docs", "docs"]

EXCLUDED_DIR_NAMES = {
    ".git",
    ".agents",
    ".claude",
    ".cursor",
    ".hg",
    ".idea",
    ".mypy_cache",
    ".ontology-agent",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".venv",
    ".pre-commit-cache",
    ".uv-cache",
    ".vscode",
    ".vite",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "node_modules",
    "saved_reports",
    "site",
    "venv",
}

EXCLUDED_FILE_NAMES = {
    ".DS_Store",
    ".env",
    "Thumbs.db",
}

DOC_EXTENSIONS = {".md", ".mdx", ".pdf", ".rst", ".txt"}

CODE_DOC_EXTENSIONS = DOC_EXTENSIONS | {
    ".cfg",
    ".css",
    ".cypher",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".mjs",
    ".py",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".ttl",
    ".yaml",
    ".yml",
}

CODE_DOC_FILE_NAMES = {
    ".dockerignore",
    ".env.example",
    ".gitignore",
    "Dockerfile",
    "Makefile",
    "alembic.ini",
    "docker-compose.yml",
    "mkdocs.yml",
    "pyproject.toml",
}


@dataclass(frozen=True)
class ImportRawResult:
    source_root: Path
    target_root: Path
    copied: int
    skipped: int
    profile: SourceProfile
    examples: list[Path] = field(default_factory=list)


def import_raw_files(
    source: Path,
    target: Path,
    *,
    profile: SourceProfile = "code-docs",
    clear: bool = False,
) -> ImportRawResult:
    source_root = _copy_source_root(source.resolve())
    target_root = target.resolve()
    if clear:
        _clear_directory(target_root)
    target_root.mkdir(parents=True, exist_ok=True)

    copied = 0
    skipped = 0
    examples: list[Path] = []
    for item in source_root.rglob("*"):
        if not item.is_file():
            continue
        if target_root in item.parents:
            skipped += 1
            continue
        relative = item.relative_to(source_root)
        if _should_skip(relative, profile):
            skipped += 1
            continue
        destination = target_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, destination)
        copied += 1
        if len(examples) < 5:
            examples.append(relative)

    return ImportRawResult(
        source_root=source_root,
        target_root=target_root,
        copied=copied,
        skipped=skipped,
        profile=profile,
        examples=examples,
    )


def _copy_source_root(source: Path) -> Path:
    if source.name == "raw":
        return source
    raw_child = source / "raw"
    if raw_child.is_dir():
        return raw_child
    return source


def _clear_directory(path: Path) -> None:
    if not path.exists():
        return
    for item in path.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def _should_skip(relative: Path, profile: SourceProfile) -> bool:
    parts = set(relative.parts[:-1])
    if parts & EXCLUDED_DIR_NAMES:
        return True
    if any(part.endswith(".egg-info") for part in parts):
        return True
    name = relative.name
    if name in EXCLUDED_FILE_NAMES or (name.startswith(".env.") and name != ".env.example"):
        return True
    if profile == "all":
        return False
    if profile == "docs":
        return relative.suffix.lower() not in DOC_EXTENSIONS
    if profile == "code-docs":
        suffix = relative.suffix.lower()
        return suffix not in CODE_DOC_EXTENSIONS and name not in CODE_DOC_FILE_NAMES
    raise ValueError(f"Unsupported source profile: {profile}")
