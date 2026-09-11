"""Đồng bộ LOCAL từ SERVER sau đợt rà soát 2 LLM (2026-09-09) — 22.121 cạnh bị sửa qua
7 rule (đồng thuận cao, khác cơ quan, VBHN, A1/A2 tin model, retry null_api, rule từ
khóa sắc thái mức độ). KHÔNG có Action node MỚI nào được tạo — tất cả là SỬA THUỘC
TÍNH trên node đã có sẵn (da_duyet, de_xuat_loai_2llm trên Action; hieu_luc_den,
action_dong trên Expression; tinh_trang, eff_to trên Norm) — nên không dùng lại
_dong_bo_local_tu_server.py (script đó chỉ xử lý Action MỚI qua diff action_id).

Cách làm: lấy tập action_id "đã bị đụng" trực tiếp từ SERVER (da_duyet=false AND
de_xuat_loai_2llm IS NOT NULL — annotation do chính đợt rà soát này ghi) làm nguồn chân
lý, rồi áp ĐÚNG cơ chế revoke+reopen+recompute+sync đã dùng 7 lần lên LOCAL — an toàn vì
Expression trên local vẫn còn action_dong=<action_id> (chưa bị đụng), y hệt trạng thái
server TRƯỚC khi sửa.

Chạy: cd genquesai/legal_rag && python _dong_bo_local_sau_rasoat_2llm.py [--apply]"""
from __future__ import annotations
import sys
import time
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient
from genquesai.legal_rag.domain.models import derive_tinh_trang

_Q_DA_SUA_TREN_SERVER = """
MATCH (a:Action) WHERE a.de_xuat_loai_2llm IS NOT NULL
RETURN a.action_id AS action_id, a.da_duyet AS da_duyet, a.de_xuat_loai_2llm AS ghi_chu
"""
_Q_DA_DUYET_LOCAL = "MATCH (a:Action {action_id:$aid}) RETURN a.da_duyet AS da_duyet"
_Q_SET_LOCAL = "MATCH (a:Action {action_id:$aid}) SET a.da_duyet=$da_duyet, a.de_xuat_loai_2llm=$ghi_chu"
_Q_MO_LAI_LOCAL = "MATCH (e:Expression {action_dong:$aid}) SET e.hieu_luc_den=null, e.action_dong=null RETURN e.expr_id AS expr_id"
_Q_TARGET_NORM = """
MATCH (a:Action {action_id:$aid})-[:AFFECTS]->(tgt)
OPTIONAL MATCH (tgt)<-[:HAS_PART*0..]-(pn:Norm)
RETURN coalesce(CASE WHEN 'Norm' IN labels(tgt) THEN tgt.norm_id ELSE null END, pn.norm_id) AS tgt_norm_id
"""
_Q_STATES = "MATCH (n:Norm {norm_id:$nid})-[:HAS_PART*]->(:Component)-[:HAS_VERSION]->(e:Expression) RETURN e.hieu_luc_tu AS tu, e.hieu_luc_den AS den"


def main(apply: bool = False) -> None:
    s = get_settings()
    s_local = s.model_copy(update={"neo4j_uri": "bolt://localhost:7687", "neo4j_user": "neo4j",
                                   "neo4j_password": "123qwe", "neo4j_database": "neo4j"})
    neo_srv = Neo4jClient(s)
    neo_loc = Neo4jClient(s_local)

    print("== Bước 1: lấy tập action_id đã bị sửa trên SERVER (nguồn chân lý) ==")
    da_sua = neo_srv.run(_Q_DA_SUA_TREN_SERVER)
    print(f"  {len(da_sua)} action đã bị đụng trên server (de_xuat_loai_2llm IS NOT NULL)")

    print("== Bước 2: lọc còn cần đồng bộ (local chưa khớp) ==")
    can_dong_bo = []
    for i, r in enumerate(da_sua):
        rows = neo_loc.run(_Q_DA_DUYET_LOCAL, aid=r["action_id"])
        if rows and rows[0]["da_duyet"] is True:  # local con nguyen, chua duoc dong bo
            can_dong_bo.append(r)
        if (i + 1) % 2000 == 0:
            print(f"  {i+1}/{len(da_sua)} đã kiểm tra")
    print(f"  Cần đồng bộ: {len(can_dong_bo)}")

    if not apply:
        print("\n== DRY RUN — chưa ghi gì. Chạy lại với --apply để thực thi. ==")
        return

    print("== Bước 3: set thuộc tính Action + mở lại Expression trên LOCAL ==")
    tgt_norm_ids: set[str] = set()
    expr_ids_mo_lai: list[str] = []
    for i, r in enumerate(can_dong_bo):
        neo_loc.run(_Q_SET_LOCAL, aid=r["action_id"], da_duyet=r["da_duyet"], ghi_chu=r["ghi_chu"])
        mo_rows = neo_loc.run(_Q_MO_LAI_LOCAL, aid=r["action_id"])
        expr_ids_mo_lai.extend(row["expr_id"] for row in mo_rows if row["expr_id"])
        tn = neo_loc.run(_Q_TARGET_NORM, aid=r["action_id"])
        if tn and tn[0]["tgt_norm_id"]:
            tgt_norm_ids.add(tn[0]["tgt_norm_id"])
        if (i + 1) % 500 == 0:
            print(f"  {i+1}/{len(can_dong_bo)} đã xử lý")
    print(f"  Đã set {len(can_dong_bo)} Action, mở lại {len(expr_ids_mo_lai)} Expression, "
         f"ảnh hưởng {len(tgt_norm_ids)} Norm")

    print("== Bước 4: tính lại tinh_trang trên LOCAL ==")
    today = date.today()
    dem_tt: dict[str, int] = {}
    for i, nid in enumerate(sorted(tgt_norm_ids)):
        states = [(r["tu"], r["den"]) for r in neo_loc.run(_Q_STATES, nid=nid)]
        tt = str(derive_tinh_trang(states, today))
        if tt == "HetHieuLuc":
            neo_loc.run("MATCH (n:Norm {norm_id:$nid}) SET n.tinh_trang=$tt", nid=nid, tt=tt)
        else:
            neo_loc.run("MATCH (n:Norm {norm_id:$nid}) SET n.tinh_trang=$tt, n.eff_to=null", nid=nid, tt=tt)
        dem_tt[tt] = dem_tt.get(tt, 0) + 1
        if (i + 1) % 500 == 0:
            print(f"  {i+1}/{len(tgt_norm_ids)} Norm đã tính lại")
    print(f"  Kết quả tinh_trang: {dem_tt}")

    print("== Bước 5: đồng bộ Qdrant LOCAL ==")
    from qdrant_client import QdrantClient
    from qdrant_client import models as qm
    q_loc = QdrantClient(url="http://127.0.0.1:6333", timeout=120, check_compatibility=False)
    CHUNK = 500
    for i in range(0, len(expr_ids_mo_lai), CHUNK):
        batch = expr_ids_mo_lai[i:i + CHUNK]
        q_loc.delete_payload(s.qdrant_collection, keys=["hieu_luc_den"],
                             points=qm.Filter(must=[qm.FieldCondition(key="expr_id", match=qm.MatchAny(any=batch))]),
                             wait=True)
        print(f"  Đã xoá payload {min(i+CHUNK, len(expr_ids_mo_lai))}/{len(expr_ids_mo_lai)}")
    print(f"  Đã đồng bộ {len(expr_ids_mo_lai)} điểm Qdrant local")
    print(f"\n=== XONG đồng bộ Neo4j local. ===")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
