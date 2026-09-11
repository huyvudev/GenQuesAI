"""Đồng bộ LOCAL cho chiều KHÔI PHỤC (khác _dong_bo_local_sau_rasoat_2llm.py — script đó
chỉ xử lý chiều revoke true→false). Nguồn chân lý: gộp 2 backup file khôi phục hôm nay
(_backup_khoi_phuc_thi_hanh_*.jsonl) — mỗi dòng có action_id + loai_moi.

Với mỗi action_id: nếu SERVER hiện da_duyet=true (đã khôi phục thành công, không rơi vào
662+167 ca "cần rà tay riêng") mà LOCAL vẫn da_duyet=false (chưa đồng bộ) -> set lại
loai + da_duyet=true + da_dong_hieu_luc=true trên local, rồi ĐÓNG LẠI hiệu lực đúng cách
(toàn bộ Norm hoặc đúng Component, tuỳ loai) y hệt logic đã dùng trên server.

Chạy: cd genquesai/legal_rag && python _dong_bo_local_khoi_phuc.py [--apply]"""
from __future__ import annotations
import glob
import json
import sys
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient
from genquesai.legal_rag.domain.models import derive_tinh_trang

TOAN_BO = {"ThayThe", "BaiBoToanBo"}
TUNG_PHAN = {"SuaDoi", "BaiBoTungPhan"}

_Q_DA_DUYET_SRV = "MATCH (a:Action {action_id:$aid}) RETURN a.da_duyet AS da_duyet, a.loai AS loai, a.de_xuat_loai_2llm AS ghi_chu"
_Q_DA_DUYET_LOC = "MATCH (a:Action {action_id:$aid}) RETURN a.da_duyet AS da_duyet"
_Q_AFFECTS = "MATCH (a:Action {action_id:$aid})-[:AFFECTS]->(tgt) RETURN labels(tgt) AS labels"
_Q_KHOI_PHUC_TOANBO = """
MATCH (a:Action {action_id:$aid})-[:ENACTED_BY]->(src:Norm)
MATCH (a)-[:AFFECTS]->(tgtn:Norm)
SET a.loai=$loai_moi, a.da_duyet=true, a.da_dong_hieu_luc=true, a.de_xuat_loai_2llm=$ghi_chu
WITH a, tgtn, src
OPTIONAL MATCH (tgtn)-[:HAS_PART*]->(:Component)-[:HAS_VERSION]->(e:Expression) WHERE e.hieu_luc_den IS NULL
FOREACH (_ IN CASE WHEN e IS NOT NULL THEN [1] ELSE [] END |
  SET e.hieu_luc_den = src.ngay_hieu_luc, e.action_dong = a.action_id)
RETURN tgtn.norm_id AS tgt_norm_id, count(e) AS n_closed
"""
_Q_KHOI_PHUC_TUNGPHAN = """
MATCH (a:Action {action_id:$aid})-[:ENACTED_BY]->(src:Norm)
MATCH (a)-[:AFFECTS]->(c:Component)
SET a.loai=$loai_moi, a.da_duyet=true, a.da_dong_hieu_luc=true, a.de_xuat_loai_2llm=$ghi_chu
WITH a, c, src
OPTIONAL MATCH (c)-[:HAS_VERSION]->(e:Expression) WHERE e.hieu_luc_den IS NULL
FOREACH (_ IN CASE WHEN e IS NOT NULL THEN [1] ELSE [] END |
  SET e.hieu_luc_den = src.ngay_hieu_luc, e.action_dong = a.action_id)
WITH a, c, count(e) AS n_closed
MATCH (pn:Norm)-[:HAS_PART*]->(c)
RETURN DISTINCT pn.norm_id AS tgt_norm_id, n_closed
"""
_Q_STATES = "MATCH (n:Norm {norm_id:$nid})-[:HAS_PART*]->(:Component)-[:HAS_VERSION]->(e:Expression) RETURN e.hieu_luc_tu AS tu, e.hieu_luc_den AS den"


def doc_action_ids_khoi_phuc() -> list[str]:
    ids = []
    for p in glob.glob("_backup_khoi_phuc_thi_hanh_*.jsonl"):
        with open(p, encoding="utf-8") as f:
            for line in f:
                ids.append(json.loads(line)["action_id"])
    return ids


def main(apply: bool = False) -> None:
    s = get_settings()
    neo_srv = Neo4jClient(s)
    s_local = s.model_copy(update={"neo4j_uri": "bolt://localhost:7687", "neo4j_user": "neo4j",
                                   "neo4j_password": "123qwe", "neo4j_database": "neo4j"})
    neo_loc = Neo4jClient(s_local)

    print("== Bước 1: lấy danh sách action_id đã khôi phục (từ backup) ==")
    action_ids = doc_action_ids_khoi_phuc()
    print(f"  {len(action_ids)} action_id trong backup")

    print("== Bước 2: lọc còn cần đồng bộ (server=true, local=false) ==")
    can_dong_bo = []
    for i, aid in enumerate(action_ids):
        srv = neo_srv.run(_Q_DA_DUYET_SRV, aid=aid)
        if not (srv and srv[0]["da_duyet"] is True):
            continue  # server chua khoi phuc thanh cong (roi vao nhom "can ra tay rieng")
        loc = neo_loc.run(_Q_DA_DUYET_LOC, aid=aid)
        if loc and loc[0]["da_duyet"] is True:
            continue  # local da dung san
        can_dong_bo.append({"action_id": aid, "loai_moi": srv[0]["loai"], "ghi_chu": srv[0]["ghi_chu"]})
        if (i + 1) % 1000 == 0:
            print(f"  {i+1}/{len(action_ids)} đã kiểm tra")
    print(f"  Cần đồng bộ: {len(can_dong_bo)}")

    if not apply:
        print("\n== DRY RUN — chưa ghi gì. Chạy lại với --apply để thực thi. ==")
        return

    print("== Bước 3: khôi phục trên LOCAL ==")
    tgt_norm_ids: set[str] = set()
    loi = 0
    for i, r in enumerate(can_dong_bo):
        aid = r["action_id"]
        aff = neo_loc.run(_Q_AFFECTS, aid=aid)
        if not aff:
            loi += 1
            continue
        is_norm = "Norm" in aff[0]["labels"]
        if r["loai_moi"] in TOAN_BO and is_norm:
            res = neo_loc.run(_Q_KHOI_PHUC_TOANBO, aid=aid, loai_moi=r["loai_moi"], ghi_chu=r["ghi_chu"])
        elif r["loai_moi"] in TUNG_PHAN and not is_norm:
            res = neo_loc.run(_Q_KHOI_PHUC_TUNGPHAN, aid=aid, loai_moi=r["loai_moi"], ghi_chu=r["ghi_chu"])
        else:
            neo_loc.run("MATCH (a:Action {action_id:$aid}) SET a.loai=$loai_moi, a.da_duyet=true, "
                       "a.de_xuat_loai_2llm=$ghi_chu", aid=aid, loai_moi=r["loai_moi"], ghi_chu=r["ghi_chu"])
            loi += 1
            continue
        for row in res:
            if row["tgt_norm_id"]:
                tgt_norm_ids.add(row["tgt_norm_id"])
        if (i + 1) % 500 == 0:
            print(f"  {i+1}/{len(can_dong_bo)} đã xử lý")
    print(f"  Đã khôi phục {len(can_dong_bo) - loi}, {loi} ca không khớp kiểu target, "
         f"ảnh hưởng {len(tgt_norm_ids)} Norm")

    print("== Bước 4: tính lại tinh_trang ==")
    today = date.today()
    dem_tt: dict[str, int] = {}
    for nid in sorted(tgt_norm_ids):
        states = [(r["tu"], r["den"]) for r in neo_loc.run(_Q_STATES, nid=nid)]
        tt = str(derive_tinh_trang(states, today))
        if tt == "HetHieuLuc":
            neo_loc.run("MATCH (n:Norm {norm_id:$nid}) SET n.tinh_trang=$tt", nid=nid, tt=tt)
        else:
            neo_loc.run("MATCH (n:Norm {norm_id:$nid}) SET n.tinh_trang=$tt, n.eff_to=null", nid=nid, tt=tt)
        dem_tt[tt] = dem_tt.get(tt, 0) + 1
    print(f"  Kết quả tinh_trang: {dem_tt}")

    print("== Bước 5: đồng bộ Qdrant LOCAL ==")
    from qdrant_client import QdrantClient
    from qdrant_client import models as qm
    q_loc = QdrantClient(url="http://127.0.0.1:6333", timeout=120, check_compatibility=False)
    theo_ngay: dict[str, list[str]] = {}
    for r in can_dong_bo:
        rows = neo_loc.run("MATCH (e:Expression {action_dong:$aid}) RETURN e.expr_id AS eid, e.hieu_luc_den AS hld",
                           aid=r["action_id"])
        for row in rows:
            if row["hld"]:
                theo_ngay.setdefault(str(row["hld"]), []).append(row["eid"])
    tong_diem = sum(len(v) for v in theo_ngay.values())
    print(f"  {tong_diem} điểm cần set ({len(theo_ngay)} nhóm theo ngày)")
    CHUNK = 500
    for hld, eids in theo_ngay.items():
        for i in range(0, len(eids), CHUNK):
            batch = eids[i:i + CHUNK]
            q_loc.set_payload(s.qdrant_collection, payload={"hieu_luc_den": hld},
                             points=qm.Filter(must=[qm.FieldCondition(key="expr_id", match=qm.MatchAny(any=batch))]),
                             wait=True)
    print(f"  Đã đồng bộ {tong_diem} điểm Qdrant local")
    print("\n=== XONG. ===")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
