from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Neo4jConnection:
    uri: str
    username: str
    password: str
    database: str = "neo4j"


class Neo4jClient:
    def __init__(self, connection: Neo4jConnection) -> None:
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("neo4j driver is not installed") from exc
        self.connection = connection
        self.driver = GraphDatabase.driver(
            connection.uri,
            auth=(connection.username, connection.password),
        )

    def close(self) -> None:
        self.driver.close()

    def verify(self) -> None:
        self.driver.verify_connectivity()

    def execute(self, cypher: str, parameters: dict[str, object] | None = None) -> None:
        with self.driver.session(database=self.connection.database) as session:
            session.run(cypher, parameters or {}).consume()

    def query(
        self, cypher: str, parameters: dict[str, object] | None = None
    ) -> list[dict[str, object]]:
        with self.driver.session(database=self.connection.database) as session:
            return [dict(record) for record in session.run(cypher, parameters or {})]

    def reset_database(self) -> None:
        self.execute("MATCH (n) DETACH DELETE n")

    def reset_project(self, project_slug: str) -> None:
        """Delete only the given project's subgraph; other projects in the DB survive."""
        statements = [
            # Graphify nodes/edges hang off this project's entities/assertions.
            "MATCH (:Project {slug: $slug})-[:HAS_ENTITY]->(:Entity)"
            "-[:DERIVED_FROM_GRAPHIFY]->(g:GraphifyNode) DETACH DELETE g",
            "MATCH (:Project {slug: $slug})-[:HAS_ASSERTION]->(:Assertion)"
            "-[:DERIVED_FROM_GRAPHIFY]->(ge:GraphifyEdge) DETACH DELETE ge",
            "MATCH (:Project {slug: $slug})-[:HAS_SOURCE]->(:Source)-[:HAS_SPAN]->(ss:SourceSpan)"
            " OPTIONAL MATCH (c:Chunk)-[:DERIVED_FROM]->(ss) DETACH DELETE ss, c",
            "MATCH (:Project {slug: $slug})-[:HAS_SOURCE]->(s:Source) DETACH DELETE s",
            "MATCH (:Project {slug: $slug})-[:HAS_ASSERTION]->(a:Assertion) DETACH DELETE a",
            "MATCH (:Project {slug: $slug})-[:HAS_ENTITY]->(e:Entity) DETACH DELETE e",
            "MATCH (:Project {slug: $slug})-[:HAS_DOMAIN]->(d)"
            " OPTIONAL MATCH (d)-[:HAS_DATASET]->(ds) DETACH DELETE d, ds",
            "MATCH (chunk:KnowledgeChunk {project_slug: $slug}) DETACH DELETE chunk",
            "MATCH (m:RagIndexMeta {project_slug: $slug}) DETACH DELETE m",
            "MATCH (p:Project {slug: $slug}) DETACH DELETE p",
        ]
        for statement in statements:
            self.execute(statement, {"slug": project_slug})
