"""Constraints + indexes Neo4j (ARCH §4.2). Idempotent (IF NOT EXISTS)."""
from __future__ import annotations

from .client import Neo4jClient

CONSTRAINTS = [
    "CREATE CONSTRAINT norm_id   IF NOT EXISTS FOR (n:Norm)           REQUIRE n.norm_id   IS UNIQUE",
    "CREATE CONSTRAINT comp_id   IF NOT EXISTS FOR (c:Component)      REQUIRE c.comp_id   IS UNIQUE",
    "CREATE CONSTRAINT expr_id   IF NOT EXISTS FOR (e:Expression)     REQUIRE e.expr_id   IS UNIQUE",
    "CREATE CONSTRAINT action_id IF NOT EXISTS FOR (a:Action)         REQUIRE a.action_id IS UNIQUE",
    "CREATE CONSTRAINT rule_id   IF NOT EXISTS FOR (r:TransitionRule) REQUIRE r.rule_id   IS UNIQUE",
    "CREATE CONSTRAINT ingestrun_id IF NOT EXISTS FOR (r:IngestRun)   REQUIRE r.run_id    IS UNIQUE",  # CDI ledger
]

INDEXES = [
    "CREATE INDEX norm_sohieu IF NOT EXISTS FOR (n:Norm)       ON (n.so_hieu)",
    "CREATE INDEX expr_tu     IF NOT EXISTS FOR (e:Expression) ON (e.hieu_luc_tu)",
    "CREATE INDEX expr_den    IF NOT EXISTS FOR (e:Expression) ON (e.hieu_luc_den)",
    "CREATE INDEX norm_hash   IF NOT EXISTS FOR (n:Norm)       ON (n.content_hash)",  # CDI dedup/resync
]

# Full-text trên tiêu đề -> tra theo TÊN THƯỜNG GỌI ("Luật Năng lượng nguyên tử") thay vì số hiệu.
FULLTEXT = [
    "CREATE FULLTEXT INDEX norm_tieu_de_ft IF NOT EXISTS FOR (n:Norm) ON EACH [n.tieu_de]",
]


def init_schema(client: Neo4jClient) -> dict:
    client.run_many(CONSTRAINTS)
    client.run_many(INDEXES)
    client.run_many(FULLTEXT)
    return {"constraints": len(CONSTRAINTS), "indexes": len(INDEXES) + len(FULLTEXT)}
