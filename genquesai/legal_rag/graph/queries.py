"""Cypher cookbook (ARCH §7). P1: point-in-time (§7.1)."""
from __future__ import annotations
import re
from datetime import date

from .client import Neo4jClient

# Ký tự đặc biệt cú pháp Lucene — $q trong db.index.fulltext.queryNodes là QUERY STRING, không
# phải literal, nên câu hỏi chứa các ký tự này (vd "/" trong số hiệu VB) làm vỡ cú pháp Lucene
# ("Lexical error", "ParseException... <EOF>"). Escape bằng backslash trước khi truyền vào.
_LUCENE_SPECIAL_RE = re.compile(r'([+\-!(){}\[\]^"~*?:\\/&|])')


def lucene_escape(s: str) -> str:
    return _LUCENE_SPECIAL_RE.sub(r"\\\1", s or "")

_POINT_IN_TIME = """
MATCH (n:Norm {so_hieu:$so_hieu})-[:HAS_PART*]->(c:Component)-[:HAS_VERSION]->(e:Expression)
WHERE ($dd IS NULL OR c.duong_dan = $dd)
  AND (e.hieu_luc_tu IS NULL OR e.hieu_luc_tu <= date($at))
  AND (e.hieu_luc_den IS NULL OR date($at) < e.hieu_luc_den)
RETURN c.duong_dan AS dieu_khoan, c.tieu_de AS tieu_de, e.text AS noi_dung,
       e.hieu_luc_tu AS tu, e.hieu_luc_den AS den, c.order_key AS ok
ORDER BY c.order_key
"""


def point_in_time(client: Neo4jClient, so_hieu: str, at: date,
                  duong_dan: str | None = None) -> list[dict]:
    """Nội dung hiện hành của 1 văn bản (hoặc 1 điều/khoản) tại ngày `at`."""
    return client.run(_POINT_IN_TIME, so_hieu=so_hieu, at=at.isoformat(), dd=duong_dan)


def norm_summary(client: Neo4jClient, so_hieu: str) -> list[dict]:
    return client.run(
        "MATCH (n:Norm {so_hieu:$s}) "
        "OPTIONAL MATCH (n)-[:HAS_PART*]->(c:Component) "
        "RETURN n.tieu_de AS tieu_de, n.loai_vb AS loai, n.ngay_hieu_luc AS hieu_luc, "
        "count(c) AS so_component", s=so_hieu)


def _native(v):
    """Chuyển neo4j.time.Date/DateTime -> python date/datetime (FastAPI serialize được)."""
    return v.to_native() if hasattr(v, "to_native") else v


def norm_meta(client: Neo4jClient, so_hieu: str) -> dict | None:
    rows = client.run(
        "MATCH (n:Norm {so_hieu:$s}) "
        "OPTIONAL MATCH (n)-[:HAS_PART*]->(c:Component) "
        "RETURN n{.*} AS n, count(c) AS so_component", s=so_hieu)
    if not rows:
        return None
    r = rows[0]
    return {**{k: _native(v) for k, v in r["n"].items()}, "so_component": r["so_component"]}


def dieu_full_text(client: Neo4jClient, so_hieu: str, duong_dan: str) -> dict | None:
    rows = client.run(
        "MATCH (:Norm {so_hieu:$s})-[:HAS_PART*]->(d:Component {duong_dan:$dd}) "
        "CALL (d) { MATCH (d)-[:HAS_PART*0..]->(x:Component)-[:HAS_VERSION]->(e:Expression) "
        "WITH x,e ORDER BY x.order_key RETURN collect(e.text) AS texts } "
        "RETURN d.tieu_de AS tieu_de, texts", s=so_hieu, dd=duong_dan)
    if not rows:
        return None
    return {"tieu_de": rows[0]["tieu_de"],
            "text": "\n".join(t for t in (rows[0]["texts"] or []) if t)}


def find_norm(client: Neo4jClient, hint: str) -> str | None:
    """Tìm so_hieu khớp (chính xác trước, rồi CONTAINS)."""
    hint = (hint or "").strip()
    if not hint:
        return None
    rows = client.run("MATCH (n:Norm) WHERE n.so_hieu=$h RETURN n.so_hieu AS s LIMIT 1", h=hint)
    if rows:
        return rows[0]["s"]
    rows = client.run("MATCH (n:Norm) WHERE n.so_hieu CONTAINS $h RETURN n.so_hieu AS s LIMIT 1", h=hint)
    return rows[0]["s"] if rows else None


def find_norms_by_name(client: Neo4jClient, name_query: str, loais: list[str],
                       top_k: int = 2, min_score: float = 4.0) -> list[str]:
    """Tra số hiệu theo TÊN THƯỜNG GỌI (full-text trên tiêu đề), LỌC theo loại VB người
    dùng nêu (tránh Thông tư/Nghị định cùng chủ đề lấn át đúng Luật). Trả ≤ top_k so_hieu
    (lấy 2 để bắt được cặp cùng tên cũ/mới, vd Luật NLNT 18/2008 + 94/2025)."""
    q = name_query.strip()
    if len(q) < 4:
        return []
    q = lucene_escape(q)
    rows = client.run(
        "CALL db.index.fulltext.queryNodes('norm_tieu_de_ft', $q) YIELD node, score "
        "WHERE node.loai_vb IN $loais AND score >= $ms "
        "RETURN node.so_hieu AS sh, score ORDER BY score DESC LIMIT $k",
        q=q, loais=loais, ms=min_score, k=top_k)
    return [r["sh"] for r in rows if r["sh"]]


def norm_relations(client: Neo4jClient, so_hieu: str) -> dict:
    def col(cypher):
        rows = client.run(cypher, s=so_hieu)
        return [r["x"] for r in rows if r["x"]]
    return {
        "bi_thay_the_boi": col("MATCH (:Norm {so_hieu:$s})<-[:REPLACES]-(m:Norm) RETURN m.so_hieu AS x"),
        "thay_the": col("MATCH (:Norm {so_hieu:$s})-[:REPLACES]->(m:Norm) RETURN m.so_hieu AS x"),
        "bi_sua_doi_boi": col("MATCH (:Norm {so_hieu:$s})<-[:AMENDS]-(m:Norm) RETURN m.so_hieu AS x"),
        "huong_dan_boi_can_cu": col("MATCH (:Norm {so_hieu:$s})-[:GUIDED_BY]->(m:Norm) RETURN m.so_hieu AS x"),
    }


def norm_transitions(client: Neo4jClient, so_hieu: str) -> list[dict]:
    return client.run(
        "MATCH (:Norm {so_hieu:$s})-[:HAS_TRANSITION]->(r:TransitionRule) "
        "RETURN r.dieu_kien AS dieu_kien, r.van_ban_ap_dung AS van_ban_ap_dung, "
        "r.nguon_dieu_khoan AS nguon, r.confidence AS confidence, r.da_duyet AS da_duyet", s=so_hieu)


def pending_transitions(client: Neo4jClient, limit: int = 100) -> list[dict]:
    return client.run(
        "MATCH (n:Norm)-[:HAS_TRANSITION]->(r:TransitionRule) WHERE r.da_duyet=false "
        "RETURN r.rule_id AS rule_id, n.so_hieu AS so_hieu, r.dieu_kien AS dieu_kien, "
        "r.van_ban_ap_dung AS van_ban_ap_dung, r.nguon_dieu_khoan AS nguon, r.confidence AS confidence "
        "ORDER BY r.confidence LIMIT $l", l=limit)


def pending_relations(client: Neo4jClient, limit: int = 100) -> list[dict]:
    """Hàng đợi REPLACES/AMENDS chờ duyệt (da_duyet=false) — cho chuyên gia rà (ARCH §1.9)."""
    return client.run(
        "MATCH (src:Norm)<-[:ENACTED_BY]-(a:Action)-[:AFFECTS]->(tgt:Norm) "
        "WHERE a.loai IN ['ThayThe','SuaDoi'] AND a.da_duyet=false "
        "RETURN a.action_id AS action_id, a.loai AS loai, a.confidence AS confidence, "
        "a.source AS source, src.so_hieu AS van_ban, tgt.so_hieu AS van_ban_dich, "
        "tgt.tieu_de AS tieu_de_dich ORDER BY a.confidence LIMIT $l", l=limit)


def pending_amendments(client: Neo4jClient, limit: int = 100, status: str | None = None) -> list[dict]:
    """Hàng đợi sửa đổi cấp Điều chưa áp/chưa duyệt (AV-3). Sắp theo status rồi confidence giảm
    (ca READY-confidence-cao lên đầu để duyệt nhanh). Lọc theo status nếu nêu."""
    return client.run(
        "MATCH (src:Norm)<-[:ENACTED_BY]-(a:Action) "
        "WHERE a.kind='amendment' AND coalesce(a.applied,false)=false "
        "  AND coalesce(a.da_duyet,false)=false AND ($st IS NULL OR a.status=$st) "
        "OPTIONAL MATCH (a)-[:AFFECTS]->(tgt:Norm) "
        "RETURN a.action_id AS action_id, a.loai AS verb, a.status AS status, "
        "a.confidence AS confidence, a.duong_dan AS duong_dan, a.grounded AS grounded, "
        "a.vbhn_confirm AS vbhn_confirm, src.so_hieu AS van_ban, "
        "coalesce(tgt.so_hieu, a.target_sh) AS van_ban_dich, a.new_text AS new_text, a.raw AS raw "
        "ORDER BY a.status, a.confidence DESC LIMIT $l", l=limit, st=status)


def amendment_stats(client: Neo4jClient) -> dict:
    """Thống kê sửa đổi cấp Điều theo status (cho cdi/observability)."""
    rows = client.run(
        "MATCH (a:Action) WHERE a.kind='amendment' "
        "RETURN a.status AS status, a.applied AS applied, count(*) AS k")
    by_status: dict[str, int] = {}
    applied = total = 0
    for r in rows:
        by_status[r["status"] or "?"] = by_status.get(r["status"] or "?", 0) + r["k"]
        total += r["k"]
        applied += r["k"] if r["applied"] else 0
    return {"total": total, "applied": applied, "pending": total - applied, "by_status": by_status}


def norm_expr_states(client: Neo4jClient, so_hieu: str) -> list[tuple]:
    rows = client.run(
        "MATCH (:Norm {so_hieu:$s})-[:HAS_PART*]->(:Component)-[:HAS_VERSION]->(e:Expression) "
        "RETURN e.hieu_luc_tu AS tu, e.hieu_luc_den AS den", s=so_hieu)
    out = []
    for r in rows:
        tu = r["tu"].to_native() if hasattr(r["tu"], "to_native") else r["tu"]
        den = r["den"].to_native() if hasattr(r["den"], "to_native") else r["den"]
        out.append((tu, den))
    return out
