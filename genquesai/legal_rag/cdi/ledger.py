"""CDI · ledger — sổ kiểm toán tập trung mọi lần nạp/đồng bộ/gỡ (CDI-1c; gỡ G6).

Mỗi lần `import`/`resync`/`undo` ghi 1 node (:IngestRun) — trả lời được
"VB nào nạp khi nào, từ nguồn gì, ai duyệt, kết quả ra sao". Là cơ sở cho
undo-import (CDI-3) và dashboard observability (CDI-5).
"""
from __future__ import annotations
import json
import uuid

from ..graph.client import Neo4jClient

CONSTRAINT = ("CREATE CONSTRAINT ingestrun_id IF NOT EXISTS "
              "FOR (r:IngestRun) REQUIRE r.run_id IS UNIQUE")


def record_run(neo: Neo4jClient, source: str, command: str, *,
               norm_ids: list[str] | None = None, n_ok: int = 0, n_fail: int = 0,
               n_dup: int = 0, n_warn: int = 0, failed: list[str] | None = None,
               validations: dict | None = None, extra: dict | None = None) -> str:
    """Ghi 1 dòng kiểm toán. Trả run_id. `validations`/`extra` -> JSON string (linh hoạt schema)."""
    run_id = uuid.uuid4().hex[:12]
    neo.run(
        "CREATE (r:IngestRun {run_id:$run_id, ts:datetime(), source:$source, command:$command, "
        "norm_ids:$norm_ids, n_ok:$n_ok, n_fail:$n_fail, n_dup:$n_dup, n_warn:$n_warn, "
        "failed:$failed, validations:$validations, extra:$extra})",
        run_id=run_id, source=source, command=command, norm_ids=norm_ids or [],
        n_ok=n_ok, n_fail=n_fail, n_dup=n_dup, n_warn=n_warn, failed=failed or [],
        validations=json.dumps(validations or {}, ensure_ascii=False),
        extra=json.dumps(extra or {}, ensure_ascii=False))
    return run_id


def list_runs(neo: Neo4jClient, limit: int = 50) -> list[dict]:
    return neo.run(
        "MATCH (r:IngestRun) RETURN r.run_id AS run_id, toString(r.ts) AS ts, r.source AS source, "
        "r.command AS command, r.n_ok AS n_ok, r.n_fail AS n_fail, r.n_dup AS n_dup, "
        "r.n_warn AS n_warn, size(r.norm_ids) AS n_norm ORDER BY r.ts DESC LIMIT $l", l=limit)


def get_run(neo: Neo4jClient, run_id: str) -> dict | None:
    rows = neo.run("MATCH (r:IngestRun {run_id:$id}) RETURN r{.*} AS r", id=run_id)
    if not rows:
        return None
    r = dict(rows[0]["r"])
    r["ts"] = str(r.get("ts"))
    for k in ("validations", "extra"):
        if isinstance(r.get(k), str):
            try:
                r[k] = json.loads(r[k])
            except json.JSONDecodeError:
                pass
    return r
