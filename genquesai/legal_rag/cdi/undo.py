"""CDI · an toàn — undo-import + prune orphan + đối soát Neo4j↔Qdrant (CDI-3; gỡ G4/G5/G7).

- undo_import: gỡ SẠCH 1 VB (Norm+Component+Expression+Action của nó+TransitionRule) khỏi graph
  + xoá point Qdrant. Dùng khi nạp nhầm. Ghi ledger.
- prune_orphans: khi re-import bản sửa, xoá Component cũ không còn trong parse mới (G4).
- consistency_check: liệt kê VB có-nội-dung nhưng THIẾU vector, và vector MỒ CÔI (norm đã xoá) (G5).

Tất định, không LLM. `raw_dir` (nếu truyền) cũng được gỡ để bulk-ingest không nạp lại.
"""
from __future__ import annotations
import shutil
from pathlib import Path

from ..graph.client import Neo4jClient

# Component/Expression của 1 Norm được namespace theo norm_id (comp_id = "{norm_id}::...") nên
# thuộc DUY NHẤT 1 Norm → xoá theo cây HAS_PART an toàn, không đụng VB khác.
_COUNT = """
MATCH (n:Norm {norm_id:$id})
OPTIONAL MATCH (n)-[:HAS_PART*]->(c:Component)
OPTIONAL MATCH (c)-[:HAS_VERSION]->(e:Expression)
OPTIONAL MATCH (n)-[:HAS_TRANSITION]->(tr:TransitionRule)
OPTIONAL MATCH (n)<-[:ENACTED_BY]-(a:Action)
RETURN count(DISTINCT c) AS comp, count(DISTINCT e) AS expr,
       count(DISTINCT tr) AS rule, count(DISTINCT a) AS act, count(n) AS norm
"""
_DELETE = """
MATCH (n:Norm {norm_id:$id})
OPTIONAL MATCH (n)-[:HAS_PART*]->(c:Component)
OPTIONAL MATCH (c)-[:HAS_VERSION]->(e:Expression)
OPTIONAL MATCH (n)-[:HAS_TRANSITION]->(tr:TransitionRule)
OPTIONAL MATCH (n)<-[:ENACTED_BY]-(a:Action)
DETACH DELETE e, c, tr, a, n
"""


def undo_import(neo: Neo4jClient, store, norm_id: str, *, raw_dir: Path | None = None,
                record: bool = True) -> dict:
    """Gỡ sạch 1 VB khỏi graph + Qdrant (+ raw dir nếu có). Trả số node/point đã xoá."""
    cnt = neo.run(_COUNT, id=norm_id)
    if not cnt or not cnt[0]["norm"]:
        return {"found": False, "norm_id": norm_id}
    c = cnt[0]
    points = store.count_by_norm(norm_id) if store is not None else 0
    if store is not None and points:
        store.delete_by_norm(norm_id)
    neo.run(_DELETE, id=norm_id)
    removed_raw = False
    if raw_dir is not None:
        d = Path(raw_dir)
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            removed_raw = True
    res = {"found": True, "norm_id": norm_id, "component": c["comp"], "expression": c["expr"],
           "transition": c["rule"], "action": c["act"], "points": points, "raw_removed": removed_raw}
    if record:
        from .ledger import record_run
        res["run_id"] = record_run(neo, source="ops", command="undo-import",
                                    norm_ids=[norm_id], n_ok=1, extra=res)
    return res


_PRUNE = """
MATCH (n:Norm {norm_id:$id})-[:HAS_PART*]->(c:Component)
WHERE NOT c.comp_id IN $keep
OPTIONAL MATCH (c)-[:HAS_VERSION]->(e:Expression)
WITH collect(DISTINCT c) AS cs, collect(DISTINCT e) AS es,
     collect(DISTINCT e.expr_id) AS eids
FOREACH (x IN es | DETACH DELETE x)
FOREACH (x IN cs | DETACH DELETE x)
RETURN size(cs) AS pruned, eids
"""


def prune_orphans(neo: Neo4jClient, store, norm_id: str, keep_comp_ids: list[str]) -> dict:
    """Xoá Component (+Expression) của VB KHÔNG còn trong parse mới (re-import bản sửa, G4).
    Đồng bộ xoá point Qdrant tương ứng theo expr_id."""
    rows = neo.run(_PRUNE, id=norm_id, keep=list(keep_comp_ids))
    pruned = rows[0]["pruned"] if rows else 0
    eids = rows[0]["eids"] if rows else []
    n_pts = 0
    if store is not None and eids:
        # xoá theo expr_id (payload) -> gồm mọi cửa sổ 'expr_id#part' của Điều dài đã re-chunk
        n_pts = store.delete_by_exprs([e for e in eids if e])
    return {"norm_id": norm_id, "pruned_components": pruned, "pruned_points": n_pts}


def consistency_check(neo: Neo4jClient, store) -> dict:
    """Đối soát Neo4j↔Qdrant (G5): VB có-nội-dung mà THIẾU vector + vector MỒ CÔI."""
    # Tiêu chí "có thể embed" khớp index.FETCH: Norm có ≥1 Component Dieu/ToanVan kèm Expression
    # (embed gộp text các Khoản/Điểm con nên không yêu cầu text riêng của Điều khác rỗng).
    embeddable = {r["norm_id"]: r["published"] for r in neo.run(
        "MATCH (n:Norm)-[:HAS_PART*]->(c:Component)-[:HAS_VERSION]->(:Expression) "
        "WHERE c.loai IN ['Dieu','ToanVan'] "
        "RETURN DISTINCT n.norm_id AS norm_id, coalesce(n.published, true) AS published")}
    all_norms = {r["norm_id"] for r in neo.run("MATCH (n:Norm) RETURN n.norm_id AS norm_id")}
    qids = store.scroll_norm_ids() if store is not None else set()
    missing = sorted(set(embeddable) - qids)
    orphan = sorted(qids - all_norms)
    return {
        "n_graph_embeddable": len(embeddable), "n_qdrant_norms": len(qids),
        "n_missing_vectors": len(missing), "n_orphan_vectors": len(orphan),
        "missing_vectors": missing[:100], "orphan_vectors": orphan[:100],
        "n_published_no_vector": sum(1 for nid in missing if embeddable.get(nid)),
        "ok": not missing and not orphan,
    }
