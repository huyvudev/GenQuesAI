"""Neo4j driver wrapper (idempotent, dùng cho cả ingest lẫn truy vấn)."""
from __future__ import annotations
import time
from typing import Any

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, SessionExpired, TransientError

from ..config import Settings, get_settings

# Dưới tải song song (nhiều luồng eval, hoặc nhiều request thật cùng lúc), kết nối tới Neo4j
# trên VPS (bolt:// qua internet, không qua tunnel) hay bị phía server/mạng chủ động đóng giữa
# chừng ("defunct connection", "forcibly closed by remote host") vì connection sống quá lâu
# trong pool mặc định (driver default max_connection_lifetime=1h). Rút ngắn lifetime để driver
# TỰ tái tạo kết nối cũ trước khi bị phía kia đóng, + retry 1 lần khi vẫn dính lỗi transient.
_POOL_KW = dict(max_connection_lifetime=280, max_connection_pool_size=50,
                connection_acquisition_timeout=30, liveness_check_timeout=30)
_RETRYABLE = (ServiceUnavailable, SessionExpired, TransientError)


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
                notifications_min_severity="OFF", **_POOL_KW)
        except (TypeError, ValueError):
            try:
                self._driver = GraphDatabase.driver(
                    s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password), **_POOL_KW)
            except (TypeError, ValueError):
                self._driver = GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))

    def verify(self) -> None:
        self._driver.verify_connectivity()

    def run(self, cypher: str, **params: Any) -> list[dict]:
        for attempt in range(2):
            try:
                with self._driver.session(database=self._database) as session:
                    return [r.data() for r in session.run(cypher, **params)]
            except _RETRYABLE:
                if attempt == 1:
                    raise
                time.sleep(0.5)
        return []  # không tới đây (raise ở attempt cuối) — chỉ để thoả type checker

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
