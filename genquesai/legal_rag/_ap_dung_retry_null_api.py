"""Áp dụng kết quả chạy lại null_api (_retry_null_api_batched_log.jsonl) — với các cạnh
giờ đã có đủ ý kiến 2 model:
  - Nếu 2 model ĐỒNG THUẬN và khác graph hiện tại -> sửa (cùng cơ chế 4 lần trước).
  - Nếu vẫn bất đồng (không phải null nữa) -> để lại, thống kê rơi vào nhóm nào để xử lý
    sau (không tự ý sửa các ca vẫn còn tranh cãi giữa 2 model).
  - Nếu vẫn null (model vẫn lỗi ở lần 2) -> để lại nguyên trạng.

CHỈ áp dụng cho action còn da_duyet=true (chưa bị rule nào khác đụng tới).

Chạy: cd genquesai/legal_rag && python _ap_dung_retry_null_api.py [--apply]
"""
from __future__ import annotations
import json
import sys
import time
from collections import Counter
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient
from genquesai.legal_rag.domain.models import derive_tinh_trang

RETRY_PATH = "_retry_null_api_batched_log.jsonl"

_Q_TARGET_NORM = """
MATCH (a:Action {action_id:$aid})-[:AFFECTS]->(tgt)
OPTIONAL MATCH (tgt)<-[:HAS_PART*0..]-(pn:Norm)
RETURN coalesce(CASE WHEN 'Norm' IN labels(tgt) THEN tgt.norm_id ELSE null END, pn.norm_id) AS tgt_norm_id
"""
_Q_MO_LAI = "MATCH (e:Expression {action_dong:$aid}) SET e.hieu_luc_den=null, e.action_dong=null RETURN e.expr_id AS expr_id"
_Q_REVOKE = "MATCH (a:Action {action_id:$aid}) SET a.da_duyet=false, a.de_xuat_loai_2llm=$ghi_chu"
_Q_STATES = "MATCH (n:Norm {norm_id:$nid})-[:HAS_PART*]->(:Component)-[:HAS_VERSION]->(e:Expression) RETURN e.hieu_luc_tu AS tu, e.hieu_luc_den AS den"
_Q_DA_DUYET = "MATCH (a:Action {action_id:$aid}) RETURN a.da_duyet AS da_duyet"


def phan_loai(ds, gm) -> str:
    if ds is None or gm is None:
        return "van_null"
    if ds != "KhongLienQuan" and gm == "KhongLienQuan":
        return "khongLienQuan_vs_that_A1"
    if gm != "KhongLienQuan" and ds == "KhongLienQuan":
        return "khongLienQuan_vs_that_A2"
    if ds == gm:
        return "dong_thuan"
    return "sac_thai_muc_do"


def main(apply: bool = False) -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    print("== Đọc kết quả chạy lại + phân loại ==")
    dem_loai = Counter()
    can_sua, khong_sua = [], []
    with open(RETRY_PATH, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("loi"):
                continue
            for r in d["ket_qua"]:
                loai = phan_loai(r["loai_deepseek"], r["loai_gemini"])
                dem_loai[loai] += 1
                if loai == "dong_thuan" and r["khac_voi_graph"]:
                    can_sua.append({**r, "norm_id": d["norm_id"]})
                elif loai != "dong_thuan":
                    khong_sua.append({**r, "norm_id": d["norm_id"], "phan_loai": loai})

    print("  Phân loại toàn bộ cạnh sau khi chạy lại:")
    for k, v in dem_loai.most_common():
        print(f"    {k}: {v}")
    print(f"  Đồng thuận VÀ khác graph hiện tại -> ứng viên sửa: {len(can_sua)}")

    # Lọc còn da_duyet=true (chưa bị rule nào khác đụng tới)
    can_sua_that = []
    for r in can_sua:
        rows = neo.run(_Q_DA_DUYET, aid=r["action_id"])
        if rows and rows[0]["da_duyet"] is True:
            can_sua_that.append(r)
    print(f"  Trong đó còn da_duyet=true (chưa xử lý): {len(can_sua_that)}")

    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_path = f"_backup_retry_null_api_{ts}.jsonl"
    with open(backup_path, "w", encoding="utf-8") as f:
        for r in can_sua_that:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  Đã ghi backup: {backup_path}")

    hang_cho_path = f"_hang_cho_sau_retry_null_api_{ts}.jsonl"
    with open(hang_cho_path, "w", encoding="utf-8") as f:
        for r in khong_sua:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  Đã ghi các ca còn bất đồng/null để xử lý sau: {hang_cho_path}")

    if not apply:
        print("\n== DRY RUN — chưa ghi gì. Chạy lại với --apply để thực thi. ==")
        return

    print("== Bước: revoke + mở lại Expression ==")
    tgt_norm_ids: set[str] = set()
    expr_ids_mo_lai: list[str] = []
    for i, r in enumerate(can_sua_that):
        tn = neo.run(_Q_TARGET_NORM, aid=r["action_id"])
        if not (tn and tn[0]["tgt_norm_id"]):
            continue
        neo.run(_Q_REVOKE, aid=r["action_id"],
               ghi_chu=f"RETRY_NULL_API_DONG_THUAN: chay lai 2 model sau khi sua loi cat cut JSON, "
                       f"dong thuan de xuat {r['loai_deepseek']}")
        mo_rows = neo.run(_Q_MO_LAI, aid=r["action_id"])
        expr_ids_mo_lai.extend(row["expr_id"] for row in mo_rows if row["expr_id"])
        tgt_norm_ids.add(tn[0]["tgt_norm_id"])
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(can_sua_that)} đã xử lý")
    print(f"  Đã revoke {len(can_sua_that)} cạnh, mở lại {len(expr_ids_mo_lai)} Expression, "
         f"ảnh hưởng {len(tgt_norm_ids)} Norm")

    print("== Tính lại tinh_trang ==")
    today = date.today()
    dem_tt: dict[str, int] = {}
    for nid in sorted(tgt_norm_ids):
        states = [(r["tu"], r["den"]) for r in neo.run(_Q_STATES, nid=nid)]
        tt = str(derive_tinh_trang(states, today))
        if tt == "HetHieuLuc":
            neo.run("MATCH (n:Norm {norm_id:$nid}) SET n.tinh_trang=$tt", nid=nid, tt=tt)
        else:
            neo.run("MATCH (n:Norm {norm_id:$nid}) SET n.tinh_trang=$tt, n.eff_to=null", nid=nid, tt=tt)
        dem_tt[tt] = dem_tt.get(tt, 0) + 1
    print(f"  Kết quả tinh_trang: {dem_tt}")

    print("== Đồng bộ Qdrant ==")
    from qdrant_client import QdrantClient
    from qdrant_client import models as qm
    q = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None,
                     timeout=s.qdrant_timeout, check_compatibility=False)
    CHUNK = 500
    for i in range(0, len(expr_ids_mo_lai), CHUNK):
        batch = expr_ids_mo_lai[i:i + CHUNK]
        q.delete_payload(s.qdrant_collection, keys=["hieu_luc_den"],
                         points=qm.Filter(must=[qm.FieldCondition(key="expr_id", match=qm.MatchAny(any=batch))]),
                         wait=True)
    print(f"  Đã đồng bộ {len(expr_ids_mo_lai)} điểm Qdrant")
    print(f"\n=== XONG. Backup tại {backup_path}. ===")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
