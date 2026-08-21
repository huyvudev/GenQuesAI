"""Reconcile ★ — đóng hiệu lực + dựng quan hệ Action/REPLACES/AMENDS (ARCH §5.2).

Nguồn chân lý cho hiệu lực: vbpl `effStatus` + `effTo` (authoritative, ARCH §4.1).
Quan hệ lập pháp: từ `references[].referenceType` (đã giải mã trên data thật):
  12 → thay thế (REPLACES)   ·   10 → sửa đổi/bổ sung (AMENDS)   ·   1 → căn cứ (GUIDED_BY)
"""
from __future__ import annotations
import json
from datetime import date, datetime
from pathlib import Path

from ..domain import TinhTrang
from ..graph.client import Neo4jClient

# referenceType -> (loai Action, loại cạnh). Giải mã trên data thật (chiều nguồn→đích):
#   12 = thay thế · 10 = sửa đổi/bổ sung · 1 = liên quan cùng loại
#   3  = VĂN BẢN CĂN CỨ (con→cha: Thông tư→Nghị định→Luật) — quan hệ "cụ thể hoá" then chốt,
#        trước đây BỊ BỎ → thủng độ phủ GUIDED_BY. Nay map để "đi theo dây" Luật→NĐ→TT được.
REL_MAP = {
    12: ("ThayThe", "REPLACES"),
    10: ("SuaDoi", "AMENDS"),
    1: ("CanCu", "GUIDED_BY"),
    3: ("CanCu", "GUIDED_BY"),
}


def _date(s) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).date()
    except (ValueError, TypeError):
        return None


def map_tinh_trang(eff: str | None) -> TinhTrang:
    e = eff or ""
    if "Hết hiệu lực một phần" in e:
        return TinhTrang.HetHieuLucMotPhan
    if "Hết hiệu lực" in e:
        return TinhTrang.HetHieuLuc
    if "Chưa có hiệu lực" in e:
        return TinhTrang.ChuaCoHieuLuc
    return TinhTrang.ConHieuLuc


def plan_for_norm(data: dict) -> dict:
    """Pure: từ doc.json data -> kế hoạch reconcile cho 1 Norm."""
    tt = map_tinh_trang((data.get("effStatus") or {}).get("name"))
    eff_to = _date(data.get("effTo"))
    # CHỈ đóng toàn bộ khi hết hiệu lực TOÀN BỘ và biết ngày (effTo). Một phần -> không đóng cứng.
    close_date = eff_to if tt is TinhTrang.HetHieuLuc else None
    relations = []
    for ref in (data.get("references") or []):
        rt = ref.get("referenceType")
        tid = (ref.get("targetDocument") or {}).get("id")
        if rt in REL_MAP and tid:
            loai, edge = REL_MAP[rt]
            relations.append((loai, edge, str(tid)))
    return {"tinh_trang": tt, "eff_to": eff_to, "close_date": close_date, "relations": relations}


_UPDATE = """
MATCH (n:Norm {norm_id:$id})
SET n.tinh_trang = $tt, n.eff_to = CASE WHEN $eff_to IS NULL THEN n.eff_to ELSE date($eff_to) END
"""
_CLOSE = """
MATCH (n:Norm {norm_id:$id})-[:HAS_PART*]->(:Component)-[:HAS_VERSION]->(e:Expression)
WHERE e.hieu_luc_den IS NULL
SET e.hieu_luc_den = date($d)
"""
# Action + cạnh quan hệ (1 query/loại cạnh; chỉ tạo nếu target có trong graph)
_REL_TMPL = """
MATCH (src:Norm {{norm_id:$sid}}), (tgt:Norm {{norm_id:$tid}})
MERGE (a:Action {{action_id:$aid}})
  SET a.loai=$loai, a.ngay_hieu_luc=src.ngay_hieu_luc, a.enacted_by=$sid,
      a.confidence=$conf, a.da_duyet=$duyet
MERGE (a)-[:ENACTED_BY]->(src)
MERGE (a)-[:AFFECTS]->(tgt)
MERGE (src)-[:{edge}]->(tgt)
"""


def sync_vector_eff(neo: Neo4jClient, store) -> int:
    """Cập nhật payload hieu_luc_den trong Qdrant theo reconcile (KHÔNG re-embed)."""
    from qdrant_client import models as qm
    rows = neo.run("MATCH (n:Norm) WHERE n.tinh_trang='HetHieuLuc' AND n.eff_to IS NOT NULL "
                   "RETURN n.norm_id AS id, toString(n.eff_to) AS effto")
    for r in rows:
        store.client.set_payload(
            store.collection, payload={"hieu_luc_den": f"{r['effto']}T00:00:00Z"},
            points=qm.Filter(must=[qm.FieldCondition(key="norm_id",
                                                     match=qm.MatchValue(value=r["id"]))]),
            wait=False)
    return len(rows)


# Hợp nhất (đặc thù VN): referenceType=7 trên VBHN trỏ tới VB gốc + VB sửa đổi đã hợp nhất.
_CONSOLIDATE = """
MATCH (v:Norm {norm_id:$vid}), (t:Norm {norm_id:$tid})
MERGE (v)-[:CONSOLIDATES]->(t)
RETURN 1
"""


def link_consolidations(neo: Neo4jClient, base: Path) -> int:
    """Tạo cạnh VBHN -[:CONSOLIDATES]-> VB gốc/sửa đổi (từ references type=7).
    Cho phép tra 'bản hợp nhất hiện hành' của một luật bị sửa nhiều lần."""
    vbhn = [r["id"] for r in neo.run(
        "MATCH (v:Norm) WHERE v.loai_vb='VanBanHopNhat' OR v.so_hieu CONTAINS 'VBHN' "
        "RETURN v.norm_id AS id")]
    n = 0
    for vid in vbhn:
        d = next(iter(base.glob(f"*/{vid}/doc.json")), None)
        if not d:
            continue
        try:
            data = json.loads(d.read_text(encoding="utf-8"))["data"]
        except Exception:
            continue
        for ref in (data.get("references") or []):
            if ref.get("referenceType") != 7:
                continue
            tid = (ref.get("targetDocument") or {}).get("id")
            if tid and neo.run(_CONSOLIDATE, vid=vid, tid=str(tid)):
                n += 1
    return n


def close_replaced(neo: Neo4jClient, action_id: str) -> dict:
    """B thay thế A (REPLACES đã duyệt) → ĐÓNG mọi Expression đang mở của A tại ngày hiệu lực B.
    An toàn: chỉ loai='ThayThe'; chỉ Expression đang mở (KHÔNG ghi đè ngày đã có); set tình trạng A."""
    info = neo.run(
        "MATCH (src:Norm)<-[:ENACTED_BY]-(a:Action {action_id:$aid})-[:AFFECTS]->(tgt:Norm) "
        "WHERE a.loai='ThayThe' AND src.ngay_hieu_luc IS NOT NULL "
        "RETURN tgt.norm_id AS tid, toString(src.ngay_hieu_luc) AS d LIMIT 1", aid=action_id)
    if not info:
        return {"closed": 0, "target": None, "eff": None}
    tid, d = info[0]["tid"], info[0]["d"]
    closed = neo.run(
        "MATCH (n:Norm {norm_id:$tid})-[:HAS_PART*]->(:Component)-[:HAS_VERSION]->(e:Expression) "
        "WHERE e.hieu_luc_den IS NULL "
        "SET e.hieu_luc_den=date($d), e.action_dong=$aid RETURN count(e) AS c",
        tid=tid, d=d, aid=action_id)[0]["c"]
    neo.run("MATCH (n:Norm {norm_id:$tid}) SET n.tinh_trang='HetHieuLuc', n.eff_to=date($d)", tid=tid, d=d)
    return {"closed": closed, "target": tid, "eff": d}


def approve_relation(neo: Neo4jClient, action_id: str, da_duyet: bool = True) -> dict:
    """Duyệt 1 quan hệ REPLACES/AMENDS. Nếu là REPLACES + duyệt → tự đóng hiệu lực VB cũ (close_replaced)."""
    info = neo.run("MATCH (a:Action {action_id:$aid}) SET a.da_duyet=$d RETURN a.loai AS loai",
                   aid=action_id, d=da_duyet)
    if not info:
        return {"action_id": action_id, "found": False}
    res = {"action_id": action_id, "da_duyet": da_duyet, "loai": info[0]["loai"], "found": True}
    if da_duyet and info[0]["loai"] == "ThayThe":
        res["auto_close"] = close_replaced(neo, action_id)
    return res


def sync_vector_norm(neo: Neo4jClient, store, norm_id: str) -> int:
    """Đồng bộ payload `hieu_luc_den` trong Qdrant cho 1 VB (sau close_replaced)."""
    from qdrant_client import models as qm
    row = neo.run("MATCH (n:Norm {norm_id:$id}) WHERE n.eff_to IS NOT NULL "
                  "RETURN toString(n.eff_to) AS d", id=norm_id)
    if not row:
        return 0
    store.client.set_payload(
        store.collection, payload={"hieu_luc_den": f"{row[0]['d']}T00:00:00Z"},
        points=qm.Filter(must=[qm.FieldCondition(key="norm_id", match=qm.MatchValue(value=norm_id))]),
        wait=False)
    return 1


def reconcile_corpus(neo: Neo4jClient, base: Path, src_dirs: list[str]) -> dict:
    doc_dirs = sorted({p.parent for sub in src_dirs for p in base.glob(f"{sub}/*/doc.json")})
    n_close = n_act = n_norm = 0
    rel_q = {edge: _REL_TMPL.format(edge=edge) for _, edge in REL_MAP.values()}
    for i, d in enumerate(doc_dirs, 1):
        try:
            data = json.loads((d / "doc.json").read_text(encoding="utf-8"))["data"]
        except Exception:
            continue
        nid = d.name
        plan = plan_for_norm(data)
        neo.run(_UPDATE, id=nid, tt=str(plan["tinh_trang"]),
                eff_to=plan["eff_to"].isoformat() if plan["eff_to"] else None)
        n_norm += 1
        if plan["close_date"]:
            neo.run(_CLOSE, id=nid, d=plan["close_date"].isoformat())
            n_close += 1
        for loai, edge, tid in plan["relations"]:
            conf = 0.9 if edge in ("REPLACES", "AMENDS") else 0.6
            neo.run(rel_q[edge], sid=nid, tid=tid, aid=f"{nid}->{tid}:{edge}",
                    loai=loai, conf=conf, duyet=conf >= 0.9)
            n_act += 1
        if i % 200 == 0:
            print(f"  {i}/{len(doc_dirs)} | norm={n_norm} closed={n_close} action={n_act}")
    return {"norm": n_norm, "closed": n_close, "action": n_act}
