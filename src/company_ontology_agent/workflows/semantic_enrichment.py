from __future__ import annotations

import re

from company_ontology_agent.graph.models import (
    Assertion,
    EntityType,
    ExtractedGraph,
    Source,
    SourceSpan,
)
from company_ontology_agent.utils.display import is_test_entity
from company_ontology_agent.utils.hashing import stable_hash
from company_ontology_agent.utils.ids import stable_id

_ARCHITECTURE_TYPES = {
    EntityType.system,
    EntityType.package,
    EntityType.module,
    EntityType.file,
    EntityType.class_,
    EntityType.data_model,
    EntityType.api_endpoint,
    EntityType.workflow,
}


def build_semantic_enrichment(
    architecture: ExtractedGraph,
    structured: ExtractedGraph,
    *,
    max_links: int = 100,
) -> ExtractedGraph:
    """Link architecture entities to structured domain types without re-extracting rows."""
    if max_links < 1:
        return ExtractedGraph(project_slug=architecture.project_slug)

    summaries = sorted(
        (
            entity
            for entity in structured.entities
            if entity.extraction_source == "structured_connector"
            and entity.metadata.get("semantic_summary")
            and entity.metadata.get("mapped_type")
        ),
        key=lambda entity: entity.id,
    )
    if not summaries:
        return ExtractedGraph(project_slug=architecture.project_slug)
    mapped_types = sorted(
        {str(summary.metadata["mapped_type"]).strip() for summary in summaries}
    )
    source = Source(
        id=stable_id("source", architecture.project_slug, "semantic-enrichment"),
        path="semantic-enrichment",
        source_type="semantic_enrichment",
        sha256=stable_hash("|".join(mapped_types)),
        title="Semantic domain alignment",
    )
    spans: list[SourceSpan] = []
    assertions: list[Assertion] = []
    for entity in sorted(architecture.entities, key=lambda item: item.id):
        if entity.type not in _ARCHITECTURE_TYPES or is_test_entity(entity):
            continue
        raw_haystack = " ".join(
            part for part in (entity.name, entity.description, entity.source_path) if part
        )
        haystack = " ".join(_tokens(raw_haystack))
        for summary in summaries:
            mapped_type = str(summary.metadata["mapped_type"]).strip()
            words = _tokens(mapped_type)
            if not words or not all(_word_matches(word, haystack) for word in words):
                continue
            evidence = f"{entity.name} references the {mapped_type} domain concept."
            span_id = stable_id("span", source.id, entity.id, mapped_type)
            spans.append(
                SourceSpan(
                    id=span_id,
                    source_id=source.id,
                    text=evidence,
                    start=0,
                    end=len(evidence),
                )
            )
            assertions.append(
                Assertion(
                    id=stable_id(
                        "assertion", entity.id, "relates_to_domain", summary.id, span_id
                    ),
                    predicate="relates_to_domain",
                    subject_id=entity.id,
                    object_id=summary.id,
                    evidence_span_id=span_id,
                    confidence=0.72,
                    extractor="semantic_enrichment",
                    extraction_source="semantic_enrichment",
                    confidence_tier="interpretive",
                    evidence_text=evidence,
                    source_path=entity.source_path,
                )
            )
            if len(assertions) >= max_links:
                break
        if len(assertions) >= max_links:
            break

    return ExtractedGraph(
        project_slug=architecture.project_slug,
        sources=[source] if assertions else [],
        source_spans=spans,
        entities=[],
        assertions=assertions,
    )


def _tokens(value: str) -> list[str]:
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return [token.lower() for token in re.findall(r"[A-Za-z0-9]+", separated) if len(token) > 2]


def _word_matches(word: str, haystack: str) -> bool:
    stem = word[:-1] if word.endswith("s") and len(word) > 4 else word
    return bool(re.search(rf"\b{re.escape(stem)}(?:s|es|ing)?\b", haystack))

