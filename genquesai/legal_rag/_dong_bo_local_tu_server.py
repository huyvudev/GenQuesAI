"""Đồng bộ LOCAL từ SERVER (production là nguồn mới nhất) — 2026-09-05.

Đo thực tế trước khi viết: Norm/Component ĐÃ KHỚP 100% giữa local/server (66.368/
2.630.398) — chỉ Action lệch (server 197.371 vs local 195.189, chênh đúng 2.182,
khớp số cạnh mới từ vụ sửa 284 VB rỗng 2026-09-04). Kiểm tra mẫu xác nhận
Expression.text KHÔNG lệch (vụ 284 VB chỉ sửa NGUỒN TEXT dùng để trích xuất tham
chiếu, không sửa lại Expression đã có trong Neo4j) — nên CHỈ CẦN đẩy các Action node
mới, không cần đụng Component/Expression.

Phần 2: bug 397 cạnh ThayThe/BaiBoToanBo phân loại sai (đã sửa trên SERVER hôm nay,
xem `_sua_253_canh_thay_the_sai.py`/`_sua_them_canh_sai_vbhn_khac.py`) — các cạnh này
đã TỒN TẠI SẴN trên local từ trước (không phải cạnh mới), nên không lọt qua diff
Action ở Phần 1 — phải CHẠY LẠI ĐỘC LẬP cùng 2 rule phát hiện đó nhắm vào LOCAL.

Chạy: cd genquesai/legal_rag && python _dong_bo_local_tu_server.py [--apply]"""
from __future__ import annotations
import sys
import time
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient
from genquesai.legal_rag.domain.models import derive_tinh_trang

_Q_ALL_ACTION_IDS = "MATCH (a:Action) RETURN a.action_id AS id"

_Q_CHI_TIET_ACTION = """
MATCH (a:Action) WHERE a.action_id IN $ids
MATCH (a)-[:ENACTED_BY]->(src:Norm)
MATCH (a)-[:AFFECTS]->(tgt)
RETURN a.action_id AS action_id, properties(a) AS props, src.norm_id AS src_norm_id,
       labels(tgt) AS tgt_labels,
       coalesce(tgt.norm_id, tgt.comp_id) AS tgt_id
"""

_Q_GHI_ACTION_NORM = """
UNWIND $rows AS r
MATCH (src:Norm {norm_id: r.src_norm_id})
MATCH (tgt:Norm {norm_id: r.tgt_id})
MERGE (a:Action {action_id: r.action_id})
SET a += r.props
MERGE (a)-[:ENACTED_BY]->(src)
MERGE (a)-[:AFFECTS]->(tgt)
"""

_Q_GHI_ACTION_COMP = """
UNWIND $rows AS r
MATCH (src:Norm {norm_id: r.src_norm_id})
MATCH (tgt:Component {comp_id: r.tgt_id})
MERGE (a:Action {action_id: r.action_id})
SET a += r.props
MERGE (a)-[:ENACTED_BY]->(src)
MERGE (a)-[:AFFECTS]->(tgt)
"""

_Q_CANH_SAI = """
MATCH (a:Action)-[:ENACTED_BY]->(src:Norm)
MATCH (a)-[:AFFECTS]->(tgt:Norm)
WHERE coalesce(a.da_duyet,false)=true AND a.loai IN ['ThayThe','BaiBoToanBo']
  AND (src.cap_bac > tgt.cap_bac OR src.loai_vb IN ['VanBanHopNhat','Khac'])
RETURN a.action_id AS action_id, tgt.norm_id AS tgt_norm_id
"""

_Q_MO_LAI = "MATCH (e:Expression) WHERE e.action_dong IN $ids SET e.hieu_luc_den=null, e.action_dong=null RETURN count(e) AS c"
_Q_REVOKE = "MATCH (a:Action) WHERE a.action_id IN $ids SET a.da_duyet=false RETURN count(a) AS c"
_Q_STATES = "MATCH (n:Norm {norm_id:$nid})-[:HAS_PART*]->(:Component)-[:HAS_VERSION]->(e:Expression) RETURN e.hieu_luc_tu AS tu, e.hieu_luc_den AS den"


def main(apply: bool = False) -> None:
    s = get_settings()
    s_local = s.model_copy(update={"neo4j_uri": "bolt://localhost:7687", "neo4j_user": "neo4j",
                                   "neo4j_password": "123qwe", "neo4j_database": "neo4j"})
    neo_srv = Neo4jClient(s)
    neo_loc = Neo4jClient(s_local)

    print("== Phần 1: đẩy Action node MỚI (chỉ có ở server) ==")
    ids_srv = {r["id"] for r in neo_srv.run(_Q_ALL_ACTION_IDS)}
    ids_loc = {r["id"] for r in neo_loc.run(_Q_ALL_ACTION_IDS)}
    moi = sorted(ids_srv - ids_loc)
    la = sorted(ids_loc - ids_srv)
    print(f"  Server: {len(ids_srv):,} · Local: {len(ids_loc):,}")
    print(f"  Action CHỈ có ở server (cần đẩy sang): {len(moi):,}")
    print(f"  Action CHỈ có ở local (bất thường, KHÔNG đụng tới): {len(la):,}")

    if apply and moi:
        CHUNK = 500
        tong_norm = tong_comp = 0
        for i in range(0, len(moi), CHUNK):
            batch = moi[i:i + CHUNK]
            rows = neo_srv.run(_Q_CHI_TIET_ACTION, ids=batch)
            rows_norm = [r for r in rows if "Norm" in r["tgt_labels"]]
            rows_comp = [r for r in rows if "Component" in r["tgt_labels"]]
            if rows_norm:
                neo_loc.run(_Q_GHI_ACTION_NORM, rows=rows_norm)
                tong_norm += len(rows_norm)
            if rows_comp:
                neo_loc.run(_Q_GHI_ACTION_COMP, rows=rows_comp)
                tong_comp += len(rows_comp)
            print(f"  Đã ghi {i+len(batch)}/{len(moi)} (đích Norm={tong_norm}, đích Component={tong_comp})")

    print("\n== Phần 2: sửa lại bug 397 cạnh ThayThe/BaiBoToanBo phân loại sai (áp cho LOCAL) ==")
    canh_sai = neo_loc.run(_Q_CANH_SAI)
    print(f"  Tìm thấy {len(canh_sai)} cạnh sai trên LOCAL (cùng rule đã dùng cho server)")
    ids_sai = [r["action_id"] for r in canh_sai]
    norm_ids_sai = sorted({r["tgt_norm_id"] for r in canh_sai})

    if apply and ids_sai:
        r1 = neo_loc.run(_Q_REVOKE, ids=ids_sai)
        print(f"  Revoke da_duyet: {r1[0]['c']}")
        r2 = neo_loc.run(_Q_MO_LAI, ids=ids_sai)
        print(f"  Mở lại Expression: {r2[0]['c']}")
        today = date.today()
        dem = {}
        for nid in norm_ids_sai:
            states = [(r["tu"], r["den"]) for r in neo_loc.run(_Q_STATES, nid=nid)]
            tt = str(derive_tinh_trang(states, today))
            if tt == "HetHieuLuc":
                neo_loc.run("MATCH (n:Norm {norm_id:$nid}) SET n.tinh_trang=$tt", nid=nid, tt=tt)
            else:
                neo_loc.run("MATCH (n:Norm {norm_id:$nid}) SET n.tinh_trang=$tt, n.eff_to=null", nid=nid, tt=tt)
            dem[tt] = dem.get(tt, 0) + 1
        print(f"  tinh_trang mới: {dem}")

    if not apply:
        print("\n== DRY RUN — chưa ghi gì. Chạy lại với --apply để thực thi. ==")
        return

    print("\n== Xác nhận sau khi sửa ==")
    norm_c = neo_loc.run("MATCH (n:Norm) RETURN count(n) AS c")[0]["c"]
    action_c = neo_loc.run("MATCH (a:Action) RETURN count(a) AS c")[0]["c"]
    print(f"  LOCAL sau đồng bộ: Norm={norm_c:,} Action={action_c:,}")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
