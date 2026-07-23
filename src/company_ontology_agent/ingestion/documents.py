"""Ingest document full text into the graph as Source/SourceSpan/Chunk nodes.

Graphify only captures per-edge evidence fragments; this stage makes whole
documents part of the canonical Neo4j graph so GraphRAG can retrieve prose
that lives deep inside long files, and so the portal can display full sources.
"""

from __future__ import annotations

from pathlib import Path

from company_ontology_agent.config.project_config import ProjectConfig
from company_ontology_agent.graph.models import (
    Chunk,
    Entity,
    EntityType,
    ExtractedGraph,
    Source,
    SourceSpan,
)
from company_ontology_agent.ingestion.raw_import import DOC_EXTENSIONS, _should_skip
from company_ontology_agent.utils.hashing import stable_hash
from company_ontology_agent.utils.ids import slugify, stable_id

# ponytail: PDFs skipped (binary, needs an extraction dep); add when a project needs them.
TEXT_DOC_EXTENSIONS = DOC_EXTENSIONS - {".pdf"}
MAX_DOC_BYTES = 2_000_000


def build_document_graph(root: Path, config: ProjectConfig) -> ExtractedGraph:
    graph = ExtractedGraph(project_slug=config.project_slug)
    input_root = (root / config.graphify.input_path).resolve()
    if not config.rag.document_chunks or not input_root.is_dir():
        return graph
    for path in sorted(input_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_DOC_EXTENSIONS:
            continue
        relative = path.relative_to(input_root)
        if _should_skip(relative, "docs"):
            continue
        if path.stat().st_size > MAX_DOC_BYTES:
            graph.warnings.append(f"Skipped oversized document: {relative}")
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            continue
        rel = relative.as_posix()
        source = Source(
            id=stable_id("source", "document", rel),
            path=rel,
            source_type="document",
            sha256=stable_hash(text),
            title=rel,
        )
        normalized = slugify(rel).replace("-", " ")
        entity = Entity(
            id=stable_id("entity", normalized, EntityType.file.value),
            type=EntityType.file,
            name=rel,
            normalized_name=normalized,
            source_path=rel,
            extraction_source="document_ingest",
            confidence_tier="extracted",
            description=f"Document {rel}",
        )
        graph.sources.append(source)
        graph.entities.append(entity)
        for ordinal, (start, end) in enumerate(
            _segments(text, config.rag.document_chunk_chars)
        ):
            segment = text[start:end].strip()
            if not segment:
                continue
            span = SourceSpan(
                id=stable_id("span", "document", rel, ordinal),
                source_id=source.id,
                start=start,
                end=end,
                text=segment,
            )
            graph.source_spans.append(span)
            graph.chunks.append(
                Chunk(
                    id=stable_id("chunk", span.id),
                    source_span_id=span.id,
                    text=segment,
                    ordinal=ordinal,
                )
            )
            entity.source_span_ids.append(span.id)
    return graph


def _segments(text: str, max_chars: int) -> list[tuple[int, int]]:
    """Pack paragraphs into windows of at most ``max_chars`` (a long paragraph is split hard)."""
    boundaries: list[tuple[int, int]] = []
    offset = 0
    for paragraph in text.split("\n\n"):
        end = offset + len(paragraph)
        if paragraph.strip():
            boundaries.append((offset, end))
        offset = end + 2
    segments: list[tuple[int, int]] = []
    window_start: int | None = None
    window_end = 0
    for start, end in boundaries:
        if window_start is None:
            window_start, window_end = start, end
        elif end - window_start <= max_chars:
            window_end = end
        else:
            segments.append((window_start, window_end))
            window_start, window_end = start, end
        while window_end - window_start > max_chars:
            segments.append((window_start, window_start + max_chars))
            window_start += max_chars
    if window_start is not None and window_end > window_start:
        segments.append((window_start, window_end))
    return segments
