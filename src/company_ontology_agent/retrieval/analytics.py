"""Schema-driven, read-only analytical retrieval over the canonical Neo4j graph."""

from __future__ import annotations

import math
import re
import time
import uuid
from typing import Any

import neo4j

from company_ontology_agent.retrieval.answerer import (
    AnalysisMetadata,
    Citation,
    QueryResponse,
)
from company_ontology_agent.retrieval.graphrag import _exact_lookup_candidates
from company_ontology_agent.utils.source_paths import source_reference

_ANALYTICAL_WORDS = re.compile(
    r"\b(most|more|least|fewest|top|bottom|how many|count|average|mean|sum|total|"
    r"minimum|maximum|highest|lowest)\b",
    re.IGNORECASE,
)
_LOWEST_WORDS = re.compile(r"\b(least|fewest|bottom|lowest|minimum)\b", re.IGNORECASE)
_RANK_WORDS = re.compile(r"\b(most|more|least|fewest|top|bottom|highest|lowest)\b", re.IGNORECASE)
_COUNT_WORDS = re.compile(r"\b(how many|count(?: distinct)?)\b", re.IGNORECASE)
_TOKEN_EQUIVALENTS = {
    "people": "person",
    "persons": "person",
    "services": "service",
    "systems": "system",
}


class Neo4jAnalyticalEngine:
    """Compile common analytical questions into fixed, parameterized Cypher shapes."""

    def __init__(
        self,
        driver: Any,
        *,
        database: str,
        max_hops: int = 3,
        max_rows: int = 100,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._driver = driver
        self._database = database
        self._max_hops = max(1, min(3, max_hops))
        self._max_rows = max(1, min(500, max_rows))
        self._timeout_seconds = timeout_seconds

    def try_answer(self, question: str, *, project_slug: str) -> QueryResponse | None:
        if not _ANALYTICAL_WORDS.search(question):
            return None
        operation = _operation(question)
        if operation not in {"rank", "count"}:
            return None
        started = time.perf_counter()
        planning_started = time.perf_counter()
        candidates = _exact_lookup_candidates(question)
        if not candidates:
            return None
        filters = self._resolve_entities(candidates, project_slug)
        if not filters:
            return None
        filter_entity = filters[0]
        signatures = self._path_signatures(str(filter_entity["id"]), project_slug)
        signature = _choose_signature(
            question, signatures, allow_direct=operation == "count"
        )
        planning_ms = (time.perf_counter() - planning_started) * 1000
        if signature is None:
            return None

        query_started = time.perf_counter()
        rows = (
            self._execute_count(
                project_slug=project_slug,
                filter_id=str(filter_entity["id"]),
                signature=signature,
            )
            if operation == "count"
            else self._execute_ranking(
                project_slug=project_slug,
                filter_id=str(filter_entity["id"]),
                signature=signature,
                ascending=bool(_LOWEST_WORDS.search(question)),
            )
        )
        query_ms = (time.perf_counter() - query_started) * 1000
        if not rows or (operation == "count" and not _as_int(rows[0].get("value"), 0)):
            return None
        return _analytical_response(
            rows,
            filter_entity=filter_entity,
            signature=signature,
            operation=operation,
            planning_ms=planning_ms,
            query_ms=query_ms,
            total_ms=(time.perf_counter() - started) * 1000,
        )

    def _execute_count(
        self,
        *,
        project_slug: str,
        filter_id: str,
        signature: dict[str, object],
    ) -> list[dict[str, object]]:
        hops = max(1, min(self._max_hops, _as_int(signature["hops"], 1)))
        query = f"""
        MATCH (project:Project {{slug: $project_slug}})-[:HAS_ENTITY]->
              (filter_entity:Entity {{id: $filter_id}})
        MATCH path=(candidate:Entity)-[relationships*{hops}..{hops}]-(filter_entity)
        WHERE coalesce(candidate.stale, false) = false
          AND coalesce(candidate.mapped_type, candidate.type, labels(candidate)[0]) = $group_type
          AND [relationship IN relationships(path) |
                toLower(coalesce(relationship.predicate, type(relationship)))] = $predicates
          AND all(relationship IN relationships(path)
                  WHERE relationship.project_slug = $project_slug
                    AND coalesce(relationship.stale, false) = false)
        RETURN $group_type AS name, count(DISTINCT candidate) AS value,
               [source IN collect(DISTINCT candidate.source_path)
                WHERE source IS NOT NULL][..3] AS source_paths,
               collect(DISTINCT coalesce(candidate.name, candidate.id) + ' → ' +
                 coalesce(filter_entity.name, filter_entity.id))[..12] AS paths,
               collect(DISTINCT [relationship IN relationships(path) |
                 coalesce(relationship.assertion_id, relationship.id)])[..12]
                 AS assertion_groups
        """
        records, _, _ = self._driver.execute_query(
            neo4j.Query(query, timeout=self._timeout_seconds),
            {
                "project_slug": project_slug,
                "filter_id": filter_id,
                "group_type": signature["group_type"],
                "predicates": signature["predicates"],
            },
            database_=self._database,
            routing_=neo4j.RoutingControl.READ,
        )
        rows = [dict(record) for record in records]
        for row in rows:
            row["type"] = signature["group_type"]
            row["id"] = ""
            row["assertion_ids"] = [
                identifier
                for group in _as_list(row.pop("assertion_groups", []))
                for identifier in _as_list(group)
            ]
        return rows

    def _resolve_entities(
        self, candidates: list[str], project_slug: str
    ) -> list[dict[str, object]]:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {slug: $project_slug})-[:HAS_ENTITY]->(entity:Entity)
            WHERE coalesce(entity.stale, false) = false
              AND (toLower(entity.name) IN $candidates
                   OR entity.normalized_name IN $candidates
                   OR any(alias IN coalesce(entity.aliases, [])
                          WHERE toLower(alias) IN $candidates))
            RETURN entity.id AS id, entity.name AS name,
                   coalesce(entity.mapped_type, entity.type, labels(entity)[0]) AS type
            ORDER BY CASE WHEN toLower(entity.name) = $candidates[0] THEN 0 ELSE 1 END,
                     size(entity.name)
            LIMIT 8
            """,
            {"project_slug": project_slug, "candidates": candidates},
            database_=self._database,
            routing_=neo4j.RoutingControl.READ,
        )
        return [dict(record) for record in records]

    def _path_signatures(self, filter_id: str, project_slug: str) -> list[dict[str, object]]:
        query = f"""
        MATCH (project:Project {{slug: $project_slug}})-[:HAS_ENTITY]->
              (filter_entity:Entity {{id: $filter_id}})
        MATCH path=(candidate:Entity)-[relationships*1..{self._max_hops}]-(filter_entity)
        WHERE candidate <> filter_entity
          AND coalesce(candidate.stale, false) = false
          AND all(node IN nodes(path) WHERE node:Entity
                  AND coalesce(node.stale, false) = false)
          AND all(relationship IN relationships
                  WHERE coalesce(relationship.stale, false) = false
                    AND relationship.project_slug = $project_slug)
        WITH coalesce(candidate.mapped_type, candidate.type, labels(candidate)[0]) AS group_type,
             [relationship IN relationships(path) |
               toLower(coalesce(relationship.predicate, type(relationship)))] AS predicates,
             [node IN nodes(path)[1..-1] |
               coalesce(node.mapped_type, node.type, labels(node)[0])] AS intermediate_types,
             length(path) AS hops
        RETURN group_type, predicates, intermediate_types, hops, count(*) AS examples
        ORDER BY examples DESC
        LIMIT 200
        """
        records, _, _ = self._driver.execute_query(
            query,
            {"project_slug": project_slug, "filter_id": filter_id},
            database_=self._database,
            routing_=neo4j.RoutingControl.READ,
        )
        return [dict(record) for record in records]

    def _execute_ranking(
        self,
        *,
        project_slug: str,
        filter_id: str,
        signature: dict[str, object],
        ascending: bool,
    ) -> list[dict[str, object]]:
        hops = max(1, min(self._max_hops, _as_int(signature["hops"], 1)))
        order = "ASC" if ascending else "DESC"
        query = f"""
        MATCH (project:Project {{slug: $project_slug}})-[:HAS_ENTITY]->
              (filter_entity:Entity {{id: $filter_id}})
        MATCH path=(candidate:Entity)-[relationships*{hops}..{hops}]-(filter_entity)
        WHERE coalesce(candidate.stale, false) = false
          AND coalesce(candidate.mapped_type, candidate.type, labels(candidate)[0]) = $group_type
          AND [relationship IN relationships(path) |
                toLower(coalesce(relationship.predicate, type(relationship)))] = $predicates
          AND all(node IN nodes(path) WHERE node:Entity
                  AND coalesce(node.stale, false) = false)
          AND all(relationship IN relationships(path)
                  WHERE relationship.project_slug = $project_slug
                    AND coalesce(relationship.stale, false) = false)
        WITH candidate, filter_entity, path,
             [node IN nodes(path)[1..-1]
              WHERE coalesce(node.mapped_type, node.type, labels(node)[0]) = $metric_type]
             AS metric_nodes
        UNWIND metric_nodes AS metric
        WITH candidate, filter_entity, count(DISTINCT metric.id) AS value,
             collect(DISTINCT coalesce(metric.source_path, candidate.source_path,
                                       filter_entity.source_path))[..3] AS source_paths,
             collect(DISTINCT coalesce(candidate.name, candidate.id) + ' → ' +
               coalesce(metric.name, metric.id) + ' → ' +
               coalesce(filter_entity.name, filter_entity.id))[..3] AS paths,
             collect(DISTINCT [relationship IN relationships(path) |
               coalesce(relationship.assertion_id, relationship.id)])[..3]
             AS assertion_groups
        RETURN candidate.id AS id, candidate.name AS name,
               coalesce(candidate.mapped_type, candidate.type, labels(candidate)[0]) AS type,
               value, [path IN source_paths WHERE path IS NOT NULL] AS source_paths,
               paths,
               reduce(ids = [], group IN assertion_groups | ids + group) AS assertion_ids
        ORDER BY value {order}, candidate.name
        LIMIT $limit
        """
        records, _, _ = self._driver.execute_query(
            neo4j.Query(query, timeout=self._timeout_seconds),
            {
                "project_slug": project_slug,
                "filter_id": filter_id,
                "group_type": signature["group_type"],
                "metric_type": signature["metric_type"],
                "predicates": signature["predicates"],
                "limit": self._max_rows,
            },
            database_=self._database,
            routing_=neo4j.RoutingControl.READ,
        )
        return [dict(record) for record in records]


def _choose_signature(
    question: str,
    signatures: list[dict[str, object]],
    *,
    allow_direct: bool = False,
) -> dict[str, object] | None:
    question_tokens = _tokens(question)
    metric_tokens = _rank_metric_tokens(question)
    ranked: list[tuple[float, dict[str, object]]] = []
    for signature in signatures:
        intermediate_types = [
            str(value) for value in _as_list(signature.get("intermediate_types"))
        ]
        if not intermediate_types and not allow_direct:
            continue
        metric_type = (
            max(
                intermediate_types,
                key=lambda value: (
                    len(metric_tokens & _tokens(value)),
                    len(question_tokens & _tokens(value)),
                ),
            )
            if intermediate_types
            else str(signature.get("group_type", "Entity"))
        )
        vocabulary = _tokens(str(signature.get("group_type", "")))
        vocabulary |= _tokens(
            " ".join(str(value) for value in _as_list(signature.get("predicates")))
        )
        vocabulary |= _tokens(" ".join(intermediate_types))
        score = float(len(question_tokens & vocabulary) * 4)
        score += len(question_tokens & _tokens(str(signature.get("group_type", "")))) * 8
        metric_overlap = len(question_tokens & _tokens(metric_type))
        score += metric_overlap * 3
        score += len(metric_tokens & _tokens(metric_type)) * 12
        score -= len(metric_tokens & _tokens(str(signature.get("group_type", "")))) * 10
        score += math.log1p(_as_int(signature.get("examples"), 0))
        score -= _as_int(signature.get("hops"), 1) * 4
        if metric_overlap and _tokens(str(signature.get("group_type", ""))) == _tokens(
            metric_type
        ):
            score -= 8
        ranked.append((score, {**signature, "metric_type": metric_type}))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], str(item[1])))
    return ranked[0][1]


def _tokens(value: str) -> set[str]:
    separated = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
    tokens = re.findall(r"[a-z0-9]+", separated.casefold())
    normalized: set[str] = set()
    for token in tokens:
        root = token.removesuffix("s")
        if root.endswith("ed") and len(root) > 4:
            root = root[:-2]
        elif root.endswith("er") and len(root) > 4:
            root = root[:-2]
        normalized.add(_TOKEN_EQUIVALENTS.get(token, root))
    return normalized


def _rank_metric_tokens(question: str) -> set[str]:
    match = re.search(
        r"\b(?:most|more|least|fewest|highest|lowest|top|bottom)\s+([\w-]+)",
        question,
        re.IGNORECASE,
    )
    return _tokens(match.group(1)) if match else set()


def _analytical_response(
    rows: list[dict[str, object]],
    *,
    filter_entity: dict[str, object],
    signature: dict[str, object],
    operation: str,
    planning_ms: float,
    query_ms: float,
    total_ms: float,
) -> QueryResponse:
    if operation == "count":
        return _count_response(
            rows,
            filter_entity=filter_entity,
            signature=signature,
            planning_ms=planning_ms,
            query_ms=query_ms,
            total_ms=total_ms,
        )
    metric_type = str(signature["metric_type"])
    leader = rows[0]
    leaders = [row for row in rows if row.get("value") == leader.get("value")]
    if len(leaders) == 1:
        answer = (
            f"**{leader['name']}** ranks first for distinct **{metric_type}** connected to "
            f"**{filter_entity['name']}**, with **{leader['value']}**."
        )
    else:
        leader_names = ", ".join(str(row["name"]) for row in leaders[:10])
        if len(leaders) > 10:
            leader_names += f", and {len(leaders) - 10} more"
        answer = (
            f"The highest observed distinct **{metric_type}** count connected to "
            f"**{filter_entity['name']}** is **{leader['value']}**. "
            f"{leader_names} share that count."
        )
    if len(rows) > 1:
        answer += "\n\n" + "\n".join(
            f"- {row['name']}: {row['value']}" for row in rows[:10]
        )
    citations: list[Citation] = []
    seen_sources: set[str] = set()
    for row in rows:
        for raw_path in _as_list(row.get("source_paths")):
            artifact, locator = source_reference(str(raw_path))
            if artifact in seen_sources:
                continue
            seen_sources.add(artifact)
            citations.append(
                Citation(
                    source_path=artifact,
                    record_locator=locator,
                    evidence=f"{row['name']}: {row['value']} distinct {metric_type} records.",
                    evidence_level="authoritative",
                )
            )
    paths = [
        {"summary": str(path)}
        for path in dict.fromkeys(
            str(path) for row in rows for path in _as_list(row.get("paths"))
        )
    ][:12]
    assertion_ids = list(
        dict.fromkeys(
            str(identifier)
            for row in rows
            for identifier in _as_list(row.get("assertion_ids"))
            if identifier
        )
    )[:12]
    return QueryResponse(
        answer=answer,
        citations=citations,
        paths=paths,
        supporting_assertions=[{"id": identifier} for identifier in assertion_ids],
        entities=[
            {"id": row["id"], "name": row["name"], "type": row["type"]}
            for row in rows[:20]
        ],
        analysis=AnalysisMetadata(
            mode="safe_analytics",
            operation="rank",
            metric=f"distinct {metric_type}",
            grouping=[str(signature["group_type"])],
            filters=[f"{filter_entity['type']} = {filter_entity['name']}"],
            rows=rows[:25],
        ),
        timings_ms={
            "planning": round(planning_ms, 2),
            "validation": 0.0,
            "database_query": round(query_ms, 2),
            "generation": 0.0,
            "total": round(total_ms, 2),
        },
        trace_id=uuid.uuid4().hex[:16],
    )


def _count_response(
    rows: list[dict[str, object]],
    *,
    filter_entity: dict[str, object],
    signature: dict[str, object],
    planning_ms: float,
    query_ms: float,
    total_ms: float,
) -> QueryResponse:
    row = rows[0]
    group_type = str(signature["group_type"])
    citations = _row_citations(rows, metric=f"distinct {group_type}")
    paths = [{"summary": str(path)} for path in _as_list(row.get("paths"))][:12]
    assertion_ids = [
        str(identifier) for identifier in _as_list(row.get("assertion_ids")) if identifier
    ][:12]
    return QueryResponse(
        answer=(
            f"There are **{row['value']} distinct {group_type}** connected to "
            f"**{filter_entity['name']}**."
        ),
        citations=citations,
        paths=paths,
        supporting_assertions=[{"id": identifier} for identifier in assertion_ids],
        analysis=AnalysisMetadata(
            mode="safe_analytics",
            operation="count",
            metric=f"distinct {group_type}",
            filters=[f"{filter_entity['type']} = {filter_entity['name']}"],
            rows=rows,
        ),
        timings_ms={
            "planning": round(planning_ms, 2),
            "validation": 0.0,
            "database_query": round(query_ms, 2),
            "generation": 0.0,
            "total": round(total_ms, 2),
        },
        trace_id=uuid.uuid4().hex[:16],
    )


def _row_citations(rows: list[dict[str, object]], *, metric: str) -> list[Citation]:
    result: list[Citation] = []
    seen: set[str] = set()
    for row in rows:
        for raw_path in _as_list(row.get("source_paths")):
            artifact, locator = source_reference(str(raw_path))
            if not artifact or artifact in seen:
                continue
            seen.add(artifact)
            result.append(
                Citation(
                    source_path=artifact,
                    record_locator=locator,
                    evidence=f"{row['name']}: {row['value']} {metric}.",
                    evidence_level="authoritative",
                )
            )
    return result


def _operation(question: str) -> str:
    if _RANK_WORDS.search(question):
        return "rank"
    if _COUNT_WORDS.search(question):
        return "count"
    return "aggregate"


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _as_int(value: object, default: int) -> int:
    if isinstance(value, int | float | str):
        try:
            return int(value)
        except ValueError:
            pass
    return default
