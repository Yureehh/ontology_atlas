from __future__ import annotations

import re
from pathlib import Path

from company_ontology_agent.extraction.provider import LLMProvider
from company_ontology_agent.extraction.schemas import StructuredExtractionPayload
from company_ontology_agent.graph.models import (
    Assertion,
    Chunk,
    Entity,
    EntityType,
    ExtractedGraph,
    Source,
    SourceSpan,
)
from company_ontology_agent.ingestion.normalizer import read_normalized_jsonl
from company_ontology_agent.ontology.mappings import normalize_predicate
from company_ontology_agent.utils.hashing import stable_hash
from company_ontology_agent.utils.ids import slugify, stable_id

TECHNOLOGY_HINTS = {
    "Alembic",
    "Aurora",
    "AWS",
    "Boto3",
    "Docker Compose",
    "Docker",
    "ECS",
    "FastAPI",
    "Graphify",
    "Graph RAG",
    "Markdown",
    "Neo4j",
    "OpenAI",
    "OWL",
    "Pillow",
    "PostgreSQL",
    "Python",
    "React",
    "RDF",
    "S3",
    "SHACL",
    "SQLAlchemy",
    "TypeScript",
    "Vite",
    "pgvector",
    "uvicorn",
}

STOP_PHRASES = {
    "the",
    "this",
}

CURATED_SINGLE_WORD_CONCEPTS = {
    "Auth",
    "Backend",
    "Conversation",
    "Database",
    "Embeddings",
    "Frontend",
    "Generali",
    "Images",
    "Reports",
    "Session",
    "Slides",
    "SlideSmith",
    "Storage",
    "Templates",
}


class LLMStructuredExtractor:
    """Deterministic strict-schema fallback extractor.

    The class is named for the future LLM adapter, but this implementation does
    not call an LLM. It emits conservative entities/assertions from normalized
    records so tests and demos are replayable without external services.
    """

    extractor_name = "local_structured_extractor"

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.provider = provider
        self.extractor_name = (
            "openai_structured_extractor" if provider else "local_structured_extractor"
        )

    def extract(self, input_path: Path, project_slug: str) -> ExtractedGraph:
        files = sorted(input_path.glob("*.jsonl")) if input_path.is_dir() else [input_path]
        graph = ExtractedGraph(project_slug=project_slug)
        for jsonl in files:
            records = read_normalized_jsonl(jsonl)
            for index, record in enumerate(records, start=1):
                source = Source(
                    id=record.source_id,
                    path=record.source_path,
                    source_type=record.source_type,
                    sha256=record.sha256,
                    title=record.title,
                )
                span = SourceSpan(
                    id=stable_id("span", record.source_id, stable_hash(record.text)),
                    source_id=record.source_id,
                    start=0,
                    end=len(record.text),
                    text=record.text[:2000],
                )
                chunk = Chunk(
                    id=stable_id("chunk", span.id, 0),
                    source_span_id=span.id,
                    text=record.text[:4000],
                    ordinal=0,
                )
                if self.provider:
                    print(
                        f"Extracting {index}/{len(records)}: {record.source_path}",
                        flush=True,
                    )
                    payload = self.provider.extract(record.text)
                    entities = self._payload_entities(payload, span.id)
                    assertions = self._payload_assertions(payload, entities, span.id)
                else:
                    entities = self._extract_entities(record.text, span.id)
                    assertions = self._extract_assertions(entities, span.id)
                graph = graph.merge(
                    ExtractedGraph(
                        project_slug=project_slug,
                        sources=[source],
                        source_spans=[span],
                        chunks=[chunk],
                        entities=entities,
                        assertions=assertions,
                    )
                )
        return graph

    def _payload_entities(
        self, payload: StructuredExtractionPayload, span_id: str
    ) -> list[Entity]:
        entities: list[Entity] = []
        for item in payload.entities:
            normalized = slugify(item.name).replace("-", " ")
            entities.append(
                Entity(
                    id=stable_id("entity", normalized, item.type.value),
                    type=item.type,
                    name=item.name,
                    normalized_name=normalized,
                    aliases=item.aliases,
                    source_span_ids=[span_id],
                )
            )
        return entities

    def _payload_assertions(
        self,
        payload: StructuredExtractionPayload,
        entities: list[Entity],
        span_id: str,
    ) -> list[Assertion]:
        by_name = {entity.normalized_name: entity for entity in entities}
        assertions: list[Assertion] = []
        for item in payload.assertions:
            subject = by_name.get(slugify(item.subject).replace("-", " "))
            object_ = by_name.get(slugify(item.object).replace("-", " "))
            if subject is None or object_ is None:
                continue
            predicate = normalize_predicate(item.predicate)
            assertions.append(
                Assertion(
                    id=stable_id("assertion", subject.id, predicate, object_.id, span_id),
                    predicate=predicate,
                    subject_id=subject.id,
                    object_id=object_.id,
                    evidence_span_id=span_id,
                    confidence=item.confidence,
                    extractor=self.extractor_name,
                )
            )
        return assertions

    def _extract_entities(self, text: str, span_id: str) -> list[Entity]:
        candidates: dict[str, EntityType] = {}
        for tech in TECHNOLOGY_HINTS:
            if re.search(rf"\b{re.escape(tech)}\b", text, flags=re.IGNORECASE):
                candidates[tech] = EntityType.technology
        for match in re.finditer(r"\b(?:Decision|Requirement|Issue|Task):\s*([^\n.]+)", text):
            label = match.group(1).strip()
            prefix = match.group(0).split(":", 1)[0].lower()
            candidates[label] = EntityType(prefix.capitalize())
        for phrase in re.findall(
            r"\b[A-Z][A-Za-z0-9]+(?:[ \t]+[A-Z][A-Za-z0-9]+){0,3}\b", text
        ):
            if _is_useful_phrase(phrase):
                candidates.setdefault(phrase, EntityType.concept)

        entities: list[Entity] = []
        for name, entity_type in sorted(candidates.items()):
            normalized = slugify(name).replace("-", " ")
            entities.append(
                Entity(
                    id=stable_id("entity", normalized, entity_type.value),
                    type=entity_type,
                    name=name,
                    normalized_name=normalized,
                    source_span_ids=[span_id],
                )
            )
        return entities

    def _extract_assertions(self, entities: list[Entity], span_id: str) -> list[Assertion]:
        assertions: list[Assertion] = []
        technologies = [entity for entity in entities if entity.type == EntityType.technology]
        decisions = [entity for entity in entities if entity.type == EntityType.decision]
        requirements = [entity for entity in entities if entity.type == EntityType.requirement]
        for decision in decisions:
            for technology in technologies:
                assertions.append(
                    Assertion(
                        id=stable_id("assertion", decision.id, "mentions", technology.id, span_id),
                        predicate="mentions",
                        subject_id=decision.id,
                        object_id=technology.id,
                        evidence_span_id=span_id,
                        confidence=0.72,
                        extractor=self.extractor_name,
                    )
                )
        for requirement in requirements:
            for technology in technologies:
                assertions.append(
                    Assertion(
                        id=stable_id(
                            "assertion", requirement.id, "requires", technology.id, span_id
                        ),
                        predicate="requires",
                        subject_id=requirement.id,
                        object_id=technology.id,
                        evidence_span_id=span_id,
                        confidence=0.72,
                        extractor=self.extractor_name,
                    )
                )
        if not assertions and len(technologies) >= 2:
            anchor = technologies[0]
            for technology in technologies[1:6]:
                assertions.append(
                    Assertion(
                        id=stable_id(
                            "assertion", anchor.id, "related_to", technology.id, span_id
                        ),
                        predicate="related_to",
                        subject_id=anchor.id,
                        object_id=technology.id,
                        evidence_span_id=span_id,
                        confidence=0.65,
                        extractor=self.extractor_name,
                    )
                )
        return assertions


def _is_useful_phrase(phrase: str) -> bool:
    normalized = phrase.lower()
    if normalized in STOP_PHRASES or len(phrase) <= 2 or len(phrase) > 64:
        return False
    tokens = phrase.split()
    if len(tokens) == 1 and phrase not in CURATED_SINGLE_WORD_CONCEPTS:
        return False
    if any(len(token) > 24 for token in tokens):
        return False
    compact = "".join(tokens)
    if re.search(r"[A-Za-z0-9]{18,}", compact):
        return False
    digits = sum(character.isdigit() for character in compact)
    if digits and digits / len(compact) > 0.2:
        return False
    letters = "".join(character for character in compact if character.isalpha())
    if len(letters) > 4 and not re.search(r"[aeiouAEIOU]", letters):
        return False
    return True
