"""Ghi Norm/Component/Expression vào Neo4j (idempotent qua MERGE — ARCH §13).

Tạo Expression với hieu_luc_tu = ngày VB có hiệu lực, hieu_luc_den = NULL (đang mở).
Việc ĐÓNG hiệu lực (set hieu_luc_den) do reconcile/Action ở P2 (ARCH §5.2).
"""
from __future__ import annotations

from .client import Neo4jClient
from ..domain import Norm
from ..ingestion.structural_parser import ParsedComponent

# 1 query: MERGE Component + Expression + HAS_VERSION + HAS_PART (parent stub inline).
# Parent được MERGE inline (stub) rồi chính dòng của nó SET props sau (UNWIND tuần tự) -> idempotent.
_COMP_CYPHER = """
UNWIND $rows AS r
MATCH (n:Norm {norm_id:$norm_id})
MERGE (c:Component {comp_id:r.comp_id})
  SET c.norm_id=$norm_id, c.loai=r.loai, c.so_thu_tu=r.so_thu_tu,
      c.duong_dan=r.duong_dan, c.tieu_de=r.tieu_de, c.order_key=r.order_key
MERGE (e:Expression {expr_id:r.expr_id})
  SET e.comp_id=r.comp_id, e.text=r.text, e.hieu_luc_tu=r.hieu_luc_tu
MERGE (c)-[:HAS_VERSION]->(e)
FOREACH (_ IN CASE WHEN r.parent IS NULL THEN [1] ELSE [] END |
  MERGE (n)-[:HAS_PART]->(c))
FOREACH (_ IN CASE WHEN r.parent IS NOT NULL THEN [1] ELSE [] END |
  MERGE (p:Component {comp_id:r.parent})
  MERGE (p)-[:HAS_PART]->(c))
"""


def _order_key(idx: int) -> int:
    """Giữ thứ tự xuất hiện để sort ổn định (duong_dan sort chuỗi không đúng số)."""
    return idx


def ingest_norm(client: Neo4jClient, norm: Norm, components: list[ParsedComponent]) -> int:
    client.run("MERGE (n:Norm {norm_id:$id}) SET n += $p", id=norm.norm_id, p=norm.to_neo4j())
    rows = []
    for i, c in enumerate(components):
        comp_id = f"{norm.norm_id}::{c.duong_dan}"
        parent = f"{norm.norm_id}::{c.parent}" if c.parent else None
        tu = norm.ngay_hieu_luc
        expr_id = f"{comp_id}@{tu.isoformat() if tu else 'NA'}"
        rows.append({
            "comp_id": comp_id, "parent": parent, "loai": c.loai,
            "so_thu_tu": c.so_thu_tu, "duong_dan": c.duong_dan, "tieu_de": c.tieu_de,
            "order_key": _order_key(i), "expr_id": expr_id, "text": c.text, "hieu_luc_tu": tu,
        })
    client.run(_COMP_CYPHER, norm_id=norm.norm_id, rows=rows)
    return len(rows)
