from __future__ import annotations

import re
import time
from collections.abc import Callable
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from company_ontology_agent.retrieval.answerer import QueryResponse
from company_ontology_agent.utils.source_paths import artifact_path


class GoldenQuestion(BaseModel):
    id: str
    question: str
    expected_entities: list[str] = Field(default_factory=list)
    expected_sources: list[str] = Field(default_factory=list)
    expected_relationships: list[str] = Field(default_factory=list)
    should_answer: bool = True


class EvaluationCase(BaseModel):
    id: str
    passed: bool
    answer_supported: bool
    expected_entities_found: bool
    expected_sources_found: bool
    expected_relationships_found: bool
    citations_valid: bool
    latency_ms: float
    failures: list[str] = Field(default_factory=list)
    trace_id: str


class EvaluationReport(BaseModel):
    total: int
    passed: int
    citation_validity: float
    entity_retrieval: float
    relationship_retrieval: float
    refusal_accuracy: float
    average_latency_ms: float
    cases: list[EvaluationCase]


def load_questions(path: Path) -> list[GoldenQuestion]:
    if not path.exists():
        raise FileNotFoundError(
            f"Golden-question suite not found: {path}. Add rag/questions.yaml first."
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [GoldenQuestion.model_validate(item) for item in data.get("questions", [])]


def evaluate_questions(
    questions: list[GoldenQuestion],
    ask: Callable[[str], QueryResponse],
    *,
    project_root: Path,
) -> EvaluationReport:
    if not questions:
        raise ValueError("Golden-question suite is empty.")

    cases: list[EvaluationCase] = []
    for question in questions:
        started = time.perf_counter()
        try:
            response = ask(question.question)
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            cases.append(
                EvaluationCase(
                    id=question.id,
                    passed=False,
                    answer_supported=False,
                    expected_entities_found=False,
                    expected_sources_found=False,
                    expected_relationships_found=False,
                    citations_valid=False,
                    latency_ms=latency_ms,
                    failures=[f"query failed: {exc}"],
                    trace_id="",
                )
            )
            continue
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        entity_tokens = {
            str(value).casefold()
            for entity in response.entities
            for value in (entity.get("id"), entity.get("name"))
            if value
        }
        cited_paths = {citation.source_path for citation in response.citations}
        expected_entities_found = all(
            entity.casefold() in entity_tokens for entity in question.expected_entities
        )
        expected_sources_found = all(source in cited_paths for source in question.expected_sources)
        path_summaries = {
            str(path.get("summary") or "").casefold() for path in response.paths
        }
        expected_relationships_found = all(
            any(expected.casefold() in summary for summary in path_summaries)
            for expected in question.expected_relationships
        )
        citations_valid = _citations_valid(question, response, project_root)
        refused = not response.citations and bool(response.warnings)
        answer_supported = refused if not question.should_answer else bool(response.citations)

        failures: list[str] = []
        if not answer_supported:
            failures.append("answer/refusal behavior did not match the expectation")
        if not expected_entities_found:
            failures.append("one or more expected entities were not retrieved")
        if not expected_sources_found:
            failures.append("one or more expected sources were not cited")
        if not expected_relationships_found:
            failures.append("one or more expected relationship paths were not retrieved")
        if not citations_valid:
            failures.append("one or more citations are invalid or unresolved")
        passed = not failures
        cases.append(
            EvaluationCase(
                id=question.id,
                passed=passed,
                answer_supported=answer_supported,
                expected_entities_found=expected_entities_found,
                expected_sources_found=expected_sources_found,
                expected_relationships_found=expected_relationships_found,
                citations_valid=citations_valid,
                latency_ms=latency_ms,
                failures=failures,
                trace_id=response.trace_id,
            )
        )

    answered = [
        case for case, question in zip(cases, questions, strict=True) if question.should_answer
    ]
    refusals = [
        case for case, question in zip(cases, questions, strict=True) if not question.should_answer
    ]
    return EvaluationReport(
        total=len(cases),
        passed=sum(case.passed for case in cases),
        citation_validity=_rate(answered, "citations_valid"),
        entity_retrieval=_rate(answered, "expected_entities_found"),
        relationship_retrieval=_rate(answered, "expected_relationships_found"),
        refusal_accuracy=_rate(refusals, "answer_supported"),
        average_latency_ms=round(sum(case.latency_ms for case in cases) / len(cases), 2),
        cases=cases,
    )


def _rate(cases: list[EvaluationCase], field: str) -> float:
    if not cases:
        return 1.0
    return round(sum(bool(getattr(case, field)) for case in cases) / len(cases), 3)


def _citations_valid(question: GoldenQuestion, response: QueryResponse, project_root: Path) -> bool:
    if not question.should_answer:
        return not response.citations
    if not response.citations:
        return False
    references = [int(number) for number in re.findall(r"\[(\d+)\]", response.answer)]
    if not references or any(
        number < 1 or number > len(response.citations) for number in references
    ):
        return False
    return all(
        _citation_resolves(
            response.citations[number - 1].source_path,
            project_root,
            question.expected_sources,
        )
        for number in set(references)
    )


def _citation_resolves(
    source_path: str,
    project_root: Path,
    expected_sources: list[str],
) -> bool:
    if source_path == "Unknown source":
        return False
    source_artifact = artifact_path(source_path)
    return (
        source_path in expected_sources
        or (project_root / source_artifact).is_file()
        or (project_root.parent / source_artifact).is_file()
    )
