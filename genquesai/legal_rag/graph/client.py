"""Neo4j driver wrapper (idempotent, dùng cho cả ingest lẫn truy vấn)."""
from __future__ import annotations
from typing import Any

from neo4j import GraphDatabase

from ..config import Settings, get_settings


class Neo4jClient:
    def __init__(self, settings: Settings | None = None):
        s = settings or get_settings()
        self._database = s.neo4j_database
        # notifications_min_severity="OFF": tắt cảnh báo "property key does not exist" của server
        # (nhiễu khi truy vấn property mới như published/content_hash trên data cũ). Fallback nếu
        # driver cũ không hỗ trợ tham số này.
        try:
            self._driver = GraphDatabase.driver(
                s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password),
                notifications_min_severity="OFF")
        except (TypeError, ValueError):
            self._driver = GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))

    def verify(self) -> None:
        self._driver.verify_connectivity()

    def run(self, cypher: str, **params: Any) -> list[dict]:
        with self._driver.session(database=self._database) as session:
            return [r.data() for r in session.run(cypher, **params)]

    def stream(self, cypher: str, **params: Any):
        """Generator: yield từng record (không materialize hết — cho embed lớn)."""
        with self._driver.session(database=self._database) as session:
            for r in session.run(cypher, **params):
                yield r.data()

    def run_many(self, statements: list[str]) -> None:
        with self._driver.session(database=self._database) as session:
            for stmt in statements:
                session.run(stmt)

    def close(self) -> None:
        self._driver.close()

    def __enter__(self) -> "Neo4jClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
