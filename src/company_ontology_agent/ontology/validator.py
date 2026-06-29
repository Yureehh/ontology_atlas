from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, XSD

from company_ontology_agent.graph.models import AssertionStatus, ExtractedGraph
from company_ontology_agent.ontology.mappings import (
    VALID_ENTITY_TYPES,
    VALID_PREDICATES,
    normalize_predicate,
)
from company_ontology_agent.ontology.shacl import validate_shacl


class ValidationIssue(BaseModel):
    item_id: str
    reason: str
    source_ref: str | None = None
    predicate: str | None = None
    subject_name: str | None = None
    object_name: str | None = None
    extractor: str | None = None
    confidence: float | None = None
    evidence_span_id: str | None = None


class ValidationResult(BaseModel):
    graph: ExtractedGraph
    rejected: list[ValidationIssue] = Field(default_factory=list)


class OntologyValidator:
    def __init__(self, project_root: Path, confidence_threshold: float = 0.5) -> None:
        self.project_root = project_root
        self.confidence_threshold = confidence_threshold

    def validate(self, graph: ExtractedGraph) -> ValidationResult:
        entity_ids = {entity.id for entity in graph.entities}
        entities_by_id = {entity.id: entity for entity in graph.entities}
        span_ids = {span.id for span in graph.source_spans}
        spans_by_id = {span.id: span for span in graph.source_spans}
        rejected: list[ValidationIssue] = []
        valid_assertions = []

        valid_entities = []
        for entity in graph.entities:
            if entity.type.value not in VALID_ENTITY_TYPES:
                rejected.append(ValidationIssue(item_id=entity.id, reason="invalid_entity_type"))
            else:
                valid_entities.append(entity)

        for assertion in graph.assertions:
            reason = None
            assertion = assertion.model_copy(
                update={"predicate": normalize_predicate(assertion.predicate)}
            )
            if (
                assertion.predicate not in VALID_PREDICATES
                and assertion.extractor != "structured_connector"
            ):
                reason = "invalid_predicate"
            elif assertion.subject_id not in entity_ids or assertion.object_id not in entity_ids:
                reason = "missing_entity"
            elif assertion.evidence_span_id not in span_ids:
                reason = "missing_evidence"
            elif assertion.confidence < self.confidence_threshold:
                reason = "confidence_below_threshold"

            if reason:
                subject = entities_by_id.get(assertion.subject_id)
                object_ = entities_by_id.get(assertion.object_id)
                span = spans_by_id.get(assertion.evidence_span_id)
                rejected.append(
                    ValidationIssue(
                        item_id=assertion.id,
                        reason=reason,
                        source_ref=span.source_id if span else None,
                        predicate=assertion.predicate,
                        subject_name=subject.name if subject else None,
                        object_name=object_.name if object_ else None,
                        extractor=assertion.extractor,
                        confidence=assertion.confidence,
                        evidence_span_id=assertion.evidence_span_id,
                    )
                )
            else:
                valid_assertions.append(
                    assertion.model_copy(update={"status": AssertionStatus.validated})
                )

        valid_graph = graph.model_copy(
            update={"entities": valid_entities, "assertions": valid_assertions}
        )
        shacl_issues = self._validate_shacl(valid_graph)
        rejected.extend(shacl_issues)
        if shacl_issues:
            valid_graph = valid_graph.model_copy(update={"assertions": []})
        self._persist_rejections(rejected)
        return ValidationResult(graph=valid_graph, rejected=rejected)

    def _persist_rejections(self, rejected: list[ValidationIssue]) -> None:
        if not rejected:
            return
        output = self.project_root / "data" / "processed" / "rejected" / "rejections.jsonl"
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as handle:
            for issue in rejected:
                handle.write(json.dumps(issue.model_dump()) + "\n")
        self._write_rejection_summary(rejected, output.parent / "summary.md")

    def _write_rejection_summary(self, rejected: list[ValidationIssue], output: Path) -> None:
        by_reason: dict[str, int] = {}
        by_predicate: dict[str, int] = {}
        for issue in rejected:
            by_reason[issue.reason] = by_reason.get(issue.reason, 0) + 1
            if issue.predicate:
                by_predicate[issue.predicate] = by_predicate.get(issue.predicate, 0) + 1
        lines = ["# Validation Rejection Summary", ""]
        lines.append("## By Reason")
        lines.append("")
        for reason, count in sorted(by_reason.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- {reason}: {count}")
        lines.extend(["", "## Top Rejected Predicates", ""])
        if by_predicate:
            for predicate, count in sorted(
                by_predicate.items(), key=lambda item: (-item[1], item[0])
            )[:25]:
                lines.append(f"- `{predicate}`: {count}")
        else:
            lines.append("- None")
        output.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _validate_shacl(self, graph: ExtractedGraph) -> list[ValidationIssue]:
        shapes_path = self.project_root / "ontology" / "shapes.ttl"
        if not shapes_path.exists():
            return []
        projection_path = self.project_root / "data" / "processed" / "ontology_projection.ttl"
        projection_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_rdf_projection(graph, projection_path)
        conforms, report = validate_shacl(projection_path, shapes_path)
        if conforms:
            return []
        report_path = self.project_root / "data" / "processed" / "rejected" / "shacl_report.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        return [
            ValidationIssue(
                item_id="shacl",
                reason="shacl_nonconformant",
                source_ref=str(report_path),
            )
        ]

    def _write_rdf_projection(self, graph: ExtractedGraph, output_path: Path) -> None:
        coa = Namespace("https://example.com/company-ontology-agent#")
        rdf = Graph()
        rdf.bind("coa", coa)
        for entity in graph.entities:
            subject = URIRef(f"{coa}{entity.id}")
            rdf.add((subject, RDF.type, coa.Entity))
            rdf.add((subject, RDF.type, URIRef(f"{coa}{entity.type.value}")))
            rdf.add((subject, coa.name, Literal(entity.name, datatype=XSD.string)))
            rdf.add((subject, coa.entityType, Literal(entity.type.value, datatype=XSD.string)))
        for assertion in graph.assertions:
            subject = URIRef(f"{coa}{assertion.id}")
            rdf.add((subject, RDF.type, coa.Assertion))
            rdf.add((subject, coa.predicate, Literal(assertion.predicate, datatype=XSD.string)))
            rdf.add((subject, coa.confidence, Literal(assertion.confidence, datatype=XSD.decimal)))
            rdf.add((subject, coa.status, Literal(assertion.status.value)))
            rdf.add(
                (
                    subject,
                    coa.evidenceSpanId,
                    Literal(assertion.evidence_span_id, datatype=XSD.string),
                )
            )
        output_path.write_text(rdf.serialize(format="turtle"), encoding="utf-8")
