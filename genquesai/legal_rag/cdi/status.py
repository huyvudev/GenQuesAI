"""CDI · observability — tổng quan sức khoẻ pipeline dữ liệu sống (CDI-5; gỡ G6).

Gộp: phân bố tình trạng hiệu lực · published/unpublished · phủ content_hash ·
lịch sử ledger · đối soát Neo4j↔Qdrant. Đủ cho 1 dashboard CLI/API mà không cần Grafana.
"""
from __future__ import annotations

from ..graph.client import Neo4jClient


def cdi_status(neo: Neo4jClient, store=None, runs: int = 5) -> dict:
    from .ledger import list_runs
    from .undo import consistency_check
    rows = neo.run("MATCH (n:Norm) RETURN n.tinh_trang AS tt, coalesce(n.published, true) AS pub, "
                   "(n.content_hash IS NOT NULL) AS hashed")
    by_tt: dict[str, int] = {}
    n_pub = n_hash = 0
    for r in rows:
        by_tt[r["tt"] or "?"] = by_tt.get(r["tt"] or "?", 0) + 1
        n_pub += 1 if r["pub"] else 0
        n_hash += 1 if r["hashed"] else 0
    from ..graph.queries import amendment_stats
    n = len(rows)
    out = {
        "norms": n, "by_tinh_trang": by_tt,
        "published": n_pub, "unpublished": n - n_pub,
        "content_hash_coverage": {"hashed": n_hash, "total": n,
                                  "pct": round(100 * n_hash / n, 1) if n else 0.0},
        "amendments": amendment_stats(neo),      # AV: sửa đổi cấp Điều theo status
        "ledger_runs": list_runs(neo, runs),
    }
    if store is not None:
        out["consistency"] = consistency_check(neo, store)
    return out
