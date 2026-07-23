from __future__ import annotations

import json
import re
import time
from typing import Any

import neo4j

from company_ontology_agent.retrieval.answer_composition import (
    GraphRAGService,
    RetrievedContext,
)

__all__ = [
    "GraphRAGService",
    "Neo4jOpenAIGenerator",
    "Neo4jVectorCypherRetriever",
    "RetrievedContext",
]


class Neo4jVectorCypherRetriever:
    """Official semantic retrieval followed by separately timed read-only traversal."""

    def __init__(
        self,
        driver: Any,
        *,
        index_name: str,
        embedder: Any,
        database: str,
        max_hops: int,
    ) -> None:
        try:
            from neo4j_graphrag.retrievers import VectorCypherRetriever
            from neo4j_graphrag.types import RetrieverResultItem
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "GraphRAG dependencies are not installed. Install company-ontology-agent[rag]."
            ) from exc

        retrieval_query = """
        WITH node, score
        WHERE node.project_slug = $project_slug
        MATCH (node)-[about:ABOUT]->(matched_entity:Entity)
        MATCH (:Project {slug: $project_slug})-[:HAS_ENTITY]->(matched_entity)
        WITH node, score, about, matched_entity ORDER BY about.ordinal
        WITH node, score, head(collect(matched_entity)) AS entity
        RETURN node.id AS chunk_id, node.text AS text,
               node.entity_id AS entity_id, coalesce(node.title, entity.name) AS entity_name,
               coalesce(node.kind, entity.mapped_type, entity.type,
                        labels(entity)[0]) AS entity_type,
               node.source_paths AS source_paths,
               node.source_span_ids AS source_span_ids,
               node.evidence_level AS evidence_level, score,
               [] AS paths, [] AS assertion_ids
        """
        hops = max(1, min(3, max_hops))
        self._exact_query = """
        MATCH (project:Project {slug: $project_slug})-[:HAS_ENTITY]->(entity:Entity)
        WHERE (toLower(entity.name) IN $candidate_names
               OR entity.normalized_name IN $candidate_names
               OR any(alias IN coalesce(entity.aliases, [])
                      WHERE toLower(alias) IN $candidate_names)
               OR any(pattern IN $candidate_patterns
                      WHERE replace(entity.name, ' ', '') =~ pattern))
          AND coalesce(entity.stale, false) = false
          AND NOT (
            entity.source_path IS NULL
            AND toLower(entity.name) = toLower(coalesce(entity.mapped_type, ''))
          )
        WITH DISTINCT entity, project
        ORDER BY CASE
                   WHEN toLower(entity.name) IN $candidate_names
                     OR entity.normalized_name IN $candidate_names
                     OR any(alias IN coalesce(entity.aliases, [])
                            WHERE toLower(alias) IN $candidate_names)
                   THEN 0 ELSE 1
                 END,
                 size(replace(entity.name, ' ', '')), entity.name
        LIMIT 4
        CALL (entity, project) {
          OPTIONAL MATCH (entity)-[relationship]-(neighbor:Entity)
          WHERE coalesce(relationship.stale, false) = false
            AND coalesce(neighbor.stale, false) = false
            AND EXISTS { MATCH (project)-[:HAS_ENTITY]->(neighbor) }
            AND (size($preferred_predicates) = 0
                 OR any(term IN $preferred_predicates WHERE
                    toLower(coalesce(relationship.predicate, type(relationship)))
                    CONTAINS term))
            AND ($preferred_direction = 'either'
                 OR ($preferred_direction = 'outgoing'
                     AND startNode(relationship) = entity)
                 OR ($preferred_direction = 'incoming'
                     AND endNode(relationship) = entity))
          WITH entity, relationship, neighbor,
               CASE
                 WHEN any(term IN $preferred_predicates WHERE
                      toLower(coalesce(relationship.predicate, type(relationship)))
                      CONTAINS term)
                      AND (($preferred_direction = 'outgoing'
                            AND startNode(relationship) = entity)
                           OR ($preferred_direction = 'incoming'
                               AND endNode(relationship) = entity)
                           OR $preferred_direction = 'either') THEN 0
                 WHEN any(term IN $preferred_predicates WHERE
                      toLower(coalesce(relationship.predicate, type(relationship)))
                      CONTAINS term) THEN 1
                 WHEN coalesce(relationship.confidence, 0) >= 0.95 THEN 2
                 WHEN relationship.extraction_source = 'structured_connector' THEN 3
                 ELSE 10
               END AS relevance
          ORDER BY relevance, neighbor.name
          LIMIT 6
          RETURN collect(CASE WHEN relationship IS NULL THEN null ELSE {
            predicate: coalesce(relationship.predicate, toLower(type(relationship))),
            neighbor_name: neighbor.name,
            direction: CASE WHEN startNode(relationship) = entity
                            THEN 'outgoing' ELSE 'incoming' END,
            source_path: coalesce(
              relationship.source_path, entity.source_path, neighbor.source_path
            ),
            assertion_id: coalesce(relationship.assertion_id, relationship.id)
          } END) AS raw_facts
        }
        RETURN entity.id AS entity_id, entity.name AS entity_name,
               coalesce(entity.mapped_type, entity.type, labels(entity)[0]) AS entity_type,
               entity.source_path AS source_path,
               entity.source_span_ids AS source_span_ids,
               entity.metadata_json AS metadata_json,
               entity.extraction_source AS extraction_source,
               [fact IN raw_facts WHERE fact IS NOT NULL] AS facts
        """
        self._traversal_query = f"""
        UNWIND $entity_ids AS entity_id
        MATCH (project:Project {{slug: $project_slug}})-[:HAS_ENTITY]->
              (entity:Entity {{id: entity_id}})
        CALL (entity, project) {{
          OPTIONAL MATCH path=(entity)-[relationships*1..{hops}]-(neighbor:Entity)
          WHERE all(item IN nodes(path) WHERE item:Entity
                    AND coalesce(item.stale, false) = false
                    AND EXISTS {{ MATCH (project)-[:HAS_ENTITY]->(item) }})
            AND all(rel IN relationships WHERE coalesce(rel.stale, false) = false)
          WITH entity, path, relationships, neighbor,
               CASE WHEN any(rel IN relationships
                 WHERE rel.extraction_source = 'structured_connector'
                    OR coalesce(rel.confidence, 0) >= 0.95) THEN 0 ELSE 1 END AS relevance
          ORDER BY relevance, length(path), neighbor.name
          LIMIT 6
          WITH collect(DISTINCT CASE WHEN path IS NULL THEN null ELSE
            CASE WHEN entity.name STARTS WITH 'oe:' OR entity.name STARTS WITH 'entity_'
              THEN coalesce(
                entity.mapped_type, entity.type, labels(entity)[0], 'Record'
              ) + ' record'
              ELSE entity.name END + ' -[' +
            reduce(types = '', rel IN relationships |
              types + CASE WHEN types = '' THEN '' ELSE ', ' END + type(rel)) +
            ']-> ' + CASE WHEN neighbor.name STARTS WITH 'oe:'
                          OR neighbor.name STARTS WITH 'entity_'
              THEN coalesce(
                neighbor.mapped_type, neighbor.type, labels(neighbor)[0], 'Record'
              ) + ' record'
              ELSE neighbor.name END END) AS paths,
            collect(DISTINCT [rel IN relationships
              WHERE coalesce(rel.assertion_id, rel.id) IS NOT NULL |
              coalesce(rel.assertion_id, rel.id)])
              AS assertion_id_groups
          RETURN paths,
                 reduce(ids = [], group IN assertion_id_groups | ids + group) AS assertion_ids
        }}
        RETURN entity.id AS entity_id,
               [path IN paths WHERE path IS NOT NULL] AS paths,
               assertion_ids
        """
        self._driver = driver
        self._database = database
        self._embedder = embedder

        def formatter(record: Any) -> Any:
            data = dict(record)
            return RetrieverResultItem(
                content=json.dumps(data, ensure_ascii=False),
                metadata={"score": data.get("score", 0.0)},
            )

        self._retriever: Any = VectorCypherRetriever(
            driver,
            index_name=index_name,
            retrieval_query=retrieval_query,
            embedder=embedder,
            result_formatter=formatter,
            neo4j_database=database,
        )
        # neo4j-graphrag 1.18 loads the vector property into
        # ``_embedding_node_property`` but filtered search reads
        # ``_node_embedding_property``. Keep project isolation enabled until the
        # upstream naming mismatch is fixed; our index invariant guarantees this
        # property is KnowledgeChunk.embedding.
        if getattr(self._retriever, "_node_embedding_property", None) is None:
            compatibility_retriever: Any = self._retriever
            compatibility_retriever._node_embedding_property = "embedding"
        # Neo4j 2026 exposes filterable fields as additional index properties,
        # while neo4j-graphrag 1.x still reads a legacy indexConfig option.
        # Index creation in KnowledgeIndexer guarantees this property when the
        # server supports SEARCH; older servers ignore it and use the procedure.
        compatibility_retriever = self._retriever
        compatibility_retriever._filterable_properties = ["project_slug"]

    def retrieve(self, question: str, *, project_slug: str, top_k: int) -> list[RetrievedContext]:
        contexts, _ = self.retrieve_with_timings(
            question, project_slug=project_slug, top_k=top_k
        )
        return contexts

    def retrieve_with_timings(
        self, question: str, *, project_slug: str, top_k: int
    ) -> tuple[list[RetrievedContext], dict[str, float]]:
        exact_started = time.perf_counter()
        exact_records: list[Any] = []
        exact_candidates = _exact_lookup_candidates(question)
        if exact_candidates:
            exact_records, _, _ = self._driver.execute_query(
                self._exact_query,
                {
                    "project_slug": project_slug,
                    "candidate_names": exact_candidates,
                    "candidate_patterns": _exact_lookup_alias_patterns(question),
                    "preferred_predicates": _preferred_predicates(question),
                    "preferred_direction": _preferred_direction(question),
                },
                database_=self._database,
                routing_=neo4j.RoutingControl.READ,
            )
        exact_ms = (time.perf_counter() - exact_started) * 1000
        exact_contexts = _exact_contexts(exact_records)
        require_path = bool(_preferred_predicates(question))
        supported_exact_contexts = [
            context
            for context in exact_contexts
            if _exact_context_has_support(context, require_path=require_path)
        ]
        if supported_exact_contexts:
            return supported_exact_contexts, {
                "exact_lookup": round(exact_ms, 2),
                "embedding": 0.0,
                "vector_search": 0.0,
                "traversal": 0.0,
            }

        embedding_started = time.perf_counter()
        query_vector = self._embedder.embed_query(question)
        embedding_ms = (time.perf_counter() - embedding_started) * 1000
        vector_started = time.perf_counter()
        result = self._retriever.search(
            query_vector=query_vector,
            top_k=top_k,
            filters={"project_slug": {"$eq": project_slug}},
            query_params={"project_slug": project_slug},
        )
        vector_ms = (time.perf_counter() - vector_started) * 1000
        contexts: list[RetrievedContext] = []
        for item in getattr(result, "items", []):
            content = getattr(item, "content", item)
            data = json.loads(content) if isinstance(content, str) else dict(content)
            contexts.append(RetrievedContext.model_validate(data))
        traversal_started = time.perf_counter()
        traversal_by_entity: dict[str, dict[str, object]] = {}
        if contexts:
            records, _, _ = self._driver.execute_query(
                self._traversal_query,
                {
                    "project_slug": project_slug,
                    "entity_ids": list(dict.fromkeys(context.entity_id for context in contexts)),
                },
                database_=self._database,
                routing_=neo4j.RoutingControl.READ,
            )
            traversal_by_entity = {
                str(record["entity_id"]): dict(record) for record in records
            }
        traversal_ms = (time.perf_counter() - traversal_started) * 1000
        contexts = [
            context.model_copy(
                update={
                    "paths": traversal_by_entity.get(context.entity_id, {}).get("paths", []),
                    "assertion_ids": traversal_by_entity.get(context.entity_id, {}).get(
                        "assertion_ids", []
                    ),
                }
            )
            for context in contexts
        ]
        return contexts, {
            "exact_lookup": round(exact_ms, 2),
            "embedding": round(embedding_ms, 2),
            "vector_search": round(vector_ms, 2),
            "traversal": round(traversal_ms, 2),
        }


def _exact_lookup_candidates(question: str) -> list[str]:
    tokens = re.findall(r"[\w][\w.'-]*", question, flags=re.UNICODE)[:64]
    sequences: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        folded = re.sub(r"['’]s$", "", token.casefold())
        named = (
            folded not in _ENTITY_QUERY_STOPWORDS
            and (
                token[0].isupper()
                or any(char.isupper() for char in token[1:])
                or token[0].isdigit()
            )
        )
        if named:
            current.append(folded)
        elif current:
            sequences.append(current)
            current = []
    if current:
        sequences.append(current)
    candidates = {
        " ".join(sequence[start : start + size])
        for sequence in sequences
        for size in range(1, len(sequence) + 1)
        for start in range(len(sequence) - size + 1)
    }
    candidates.update(_question_entity_phrases(question))
    if not candidates:
        residual = [
            token.casefold()
            for token in tokens
            if token.casefold() not in _ENTITY_QUERY_STOPWORDS
        ]
        if len(residual) == 1:
            candidates.add(residual[0])
    return sorted(candidates, key=lambda value: (-len(value), value))


def _question_entity_phrases(question: str) -> set[str]:
    """Extract complete entity phrases without discarding internal stopwords."""
    patterns = (
        r"\bdoes\s+(.+?)\s+(?:play|compete|belong|use|inherit)\b",
        r"\b(?:play|plays|played)\s+for\s+(.+?)(?:[?.!]|$)",
        r"\b(?:compete|competes)\s+in\s+(.+?)(?:[?.!]|$)",
        r"^(.+?)[’']s\b",
    )
    phrases: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, question, flags=re.IGNORECASE):
            phrase = match.group(1).strip(" \t\r\n?.!").casefold()
            if phrase:
                phrases.add(phrase)
    return phrases


def _exact_lookup_alias_patterns(question: str) -> list[str]:
    """Return safe ordered-subsequence patterns for explicit uppercase acronyms."""
    acronyms = re.findall(r"(?<!\w)[A-Z][A-Z0-9]{1,5}(?!\w)", question)
    return ["(?i).*" + ".*".join(map(re.escape, acronym)) + ".*" for acronym in acronyms]


def _preferred_predicates(question: str) -> list[str]:
    ignored = {
        "what", "which", "who", "where", "when", "does", "did", "is", "are",
        "the", "for", "from", "with", "about", "into", "onto", "this", "that",
    }
    terms = [
        token.removesuffix("s")
        for token in re.findall(r"[a-z0-9]+", question.casefold())
        if len(token) >= 3 and token not in ignored
    ]
    return list(dict.fromkeys(terms))[:8]


def _preferred_direction(question: str) -> str:
    lowered = question.casefold()
    if re.search(
        r"\b(?:who|which\s+players?)\s+(?:currently\s+)?plays?\s+for\b", lowered
    ):
        return "incoming"
    if re.search(r"\b(what|which)\s+(uses|inherits|plays)\b", lowered):
        return "incoming"
    if re.search(r"\b(what|which)\b.*\bdoes\b", lowered):
        return "outgoing"
    return "outgoing"


_ENTITY_QUERY_STOPWORDS = {
    "a",
    "about",
    "affected",
    "an",
    "and",
    "are",
    "artifact",
    "artifacts",
    "authoritative",
    "business",
    "by",
    "belong",
    "belongs",
    "can",
    "change",
    "changes",
    "code",
    "contain",
    "contains",
    "compete",
    "competes",
    "contribute",
    "could",
    "data",
    "dataset",
    "datasets",
    "dependencies",
    "dependency",
    "did",
    "do",
    "does",
    "entities",
    "entity",
    "evidence",
    "file",
    "files",
    "for",
    "from",
    "graph",
    "how",
    "impact",
    "in",
    "inherit",
    "inherits",
    "is",
    "mapping",
    "mappings",
    "me",
    "model",
    "models",
    "module",
    "modules",
    "of",
    "on",
    "play",
    "played",
    "plays",
    "relationship",
    "relationships",
    "should",
    "show",
    "source",
    "sources",
    "structured",
    "system",
    "systems",
    "tell",
    "the",
    "to",
    "use",
    "uses",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "would",
}


def _exact_contexts(records: list[Any]) -> list[RetrievedContext]:
    contexts: list[RetrievedContext] = []
    for record in records:
        data = dict(record)
        entity_name = str(data.get("entity_name") or "")
        if not entity_name:
            continue
        facts_value = data.get("facts")
        facts = [dict(fact) for fact in facts_value] if isinstance(facts_value, list) else []
        paths: list[str] = []
        assertion_ids: list[str] = []
        source_paths = [str(data["source_path"])] if data.get("source_path") else []
        for fact in facts:
            predicate = str(fact.get("predicate") or "related_to")
            neighbor = str(fact.get("neighbor_name") or "")
            if not neighbor:
                continue
            if fact.get("direction") == "incoming":
                paths.append(f"{neighbor} -[{predicate}]-> {entity_name}")
            else:
                paths.append(f"{entity_name} -[{predicate}]-> {neighbor}")
            if fact.get("assertion_id"):
                assertion_ids.append(str(fact["assertion_id"]))
            if fact.get("source_path"):
                source_paths.append(str(fact["source_path"]))

        metadata = _metadata_values(data.get("metadata_json"))
        text_lines = [
            f"Entity: {entity_name}",
            f"Type: {data.get('entity_type') or 'Entity'}",
        ]
        if metadata:
            text_lines.append(
                "Structured attributes: "
                + ", ".join(f"{key}={value}" for key, value in metadata.items())
            )
        if paths:
            text_lines.append("Relationships:\n- " + "\n- ".join(dict.fromkeys(paths)))
        source_span_ids = data.get("source_span_ids")
        contexts.append(
            RetrievedContext(
                chunk_id=f"exact:{data.get('entity_id')}",
                text="\n".join(text_lines),
                entity_id=str(data.get("entity_id") or ""),
                entity_name=entity_name,
                entity_type=str(data.get("entity_type") or "Entity"),
                source_paths=list(dict.fromkeys(source_paths)),
                evidence_level=(
                    "authoritative"
                    if data.get("extraction_source") == "structured_connector"
                    else "evidence_backed"
                ),
                score=1.0,
                paths=list(dict.fromkeys(paths)),
                source_span_ids=(
                    [str(value) for value in source_span_ids]
                    if isinstance(source_span_ids, list)
                    else []
                ),
                assertion_ids=list(dict.fromkeys(assertion_ids)),
            )
        )
    return contexts


def _exact_context_has_support(context: RetrievedContext, *, require_path: bool) -> bool:
    return bool(context.paths or (not require_path and "Structured attributes:" in context.text))


def _metadata_values(raw: object) -> dict[str, str]:
    try:
        metadata = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return {}
    if not isinstance(metadata, dict):
        return {}
    hidden = {
        "_origin",
        "community",
        "community_id",
        "connector",
        "dataset_sources",
        "datasets",
        "file_type",
        "id",
        "label",
        "mapped_type",
        "norm_label",
        "record_key",
        "row_number",
        "run_id",
        "seen_at",
        "source",
        "source_file",
        "source_location",
        "source_paths",
    }
    keys = sorted(metadata)
    values: dict[str, str] = {}
    for key in keys:
        value = metadata.get(key)
        if key in hidden or not isinstance(value, (str, int, float, bool)) or value == "":
            continue
        values[key] = str(value)
        if len(values) == 12:
            break
    return values


class Neo4jOpenAIGenerator:
    def __init__(self, *, model_name: str, api_key: str | None = None) -> None:
        try:
            from neo4j_graphrag.llm import OpenAILLM
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "GraphRAG dependencies are not installed. Install company-ontology-agent[rag]."
            ) from exc
        if api_key:
            self._llm: Any = OpenAILLM(
                model_name=model_name,
                api_key=api_key,
                timeout=45.0,
                max_retries=1,
                model_params={
                    "max_completion_tokens": 1000,
                    "reasoning_effort": "none",
                },
            )
        else:
            self._llm = OpenAILLM(
                model_name=model_name,
                timeout=45.0,
                max_retries=1,
                model_params={
                    "max_completion_tokens": 1000,
                    "reasoning_effort": "none",
                },
            )

    def generate(self, prompt: str) -> str:
        response = self._llm.invoke(prompt)
        return str(getattr(response, "content", response))

    @property
    def llm(self) -> Any:
        return self._llm
