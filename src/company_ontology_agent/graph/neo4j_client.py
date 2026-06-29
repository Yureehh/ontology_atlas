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
