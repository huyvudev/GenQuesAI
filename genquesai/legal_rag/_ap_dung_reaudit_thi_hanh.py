"""Áp dụng kết quả re-audit "Điều khoản thi hành" (_reaudit_thi_hanh_log.jsonl) — cho
2.601 cạnh 2 model đồng thuận VÀ khác graph hiện tại. 416 cạnh còn bất đồng để riêng,
xử lý sau (quy mô nhỏ).

Cùng cơ chế: revoke da_duyet + mở lại Expression + tính lại tinh_trang + đồng bộ Qdrant.

Chạy: cd genquesai/legal_rag && python _ap_dung_reaudit_thi_hanh.py [--apply]
"""
from __future__ import annotations
import json
import sys
import time
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient
from genquesai.legal_rag.domain.models import derive_tinh_trang

LOG_PATH = "_reaudit_thi_hanh_log.jsonl"

_Q_TARGET_NORM = """
MATCH (a:Action {action_id:$aid})-[:AFFECTS]->(tgt)
OPTIONAL MATCH (tgt)<-[:HAS_PART*0..]-(pn:Norm) WHERE 'Component' IN labels(tgt)
RETURN coalesce(CASE WHEN 'Norm' IN labels(tgt) THEN tgt.norm_id ELSE null END, pn.norm_id) AS tgt_norm_id
"""
_Q_MO_LAI = "MATCH (e:Expression {action_dong:$aid}) SET e.hieu_luc_den=null, e.action_dong=null RETURN e.expr_id AS expr_id"
_Q_REVOKE = "MATCH (a:Action {action_id:$aid}) SET a.da_duyet=false, a.de_xuat_loai_2llm=$ghi_chu"
_Q_STATES = "MATCH (n:Norm {norm_id:$nid})-[:HAS_PART*]->(:Component)-[:HAS_VERSION]->(e:Expression) RETURN e.hieu_luc_tu AS tu, e.hieu_luc_den AS den"
_Q_DA_DUYET = "MATCH (a:Action {action_id:$aid}) RETURN a.da_duyet AS da_duyet"


def doc_ung_vien() -> tuple[list[dict], list[dict]]:
    dong_thuan_khac, bat_dong = [], []
    with open(LOG_PATH, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("loi"):
                continue
            for r in d["ket_qua"]:
                ds, gm = r["loai_deepseek"], r["loai_gemini"]
                if ds is None or gm is None:
                    continue
                if r["dong_thuan_2_model"]:
                    if ds != r["loai_hien_tai_graph"]:
                        dong_thuan_khac.append({**r, "norm_id": d["norm_id"], "so_hieu_nguon": d["so_hieu_nguon"]})
                else:
                    bat_dong.append({**r, "norm_id": d["norm_id"], "so_hieu_nguon": d["so_hieu_nguon"]})
    return dong_thuan_khac, bat_dong


def main(apply: bool = False) -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    print("== Bước 1: lọc ứng viên đồng thuận khác graph (bỏ qua đã bị rule khác đụng tới) ==")
    dong_thuan_khac, bat_dong = doc_ung_vien()
    print(f"  {len(dong_thuan_khac)} cạnh đồng thuận khác graph (ứng viên sửa)")
    print(f"  {len(bat_dong)} cạnh vẫn bất đồng (để riêng, ghi ra file rà tay)")

    can_sua = []
    for r in dong_thuan_khac:
        rows = neo.run(_Q_DA_DUYET, aid=r["action_id"])
        if not (rows and rows[0]["da_duyet"] is True):
            continue
        tn = neo.run(_Q_TARGET_NORM, aid=r["action_id"])
        if tn and tn[0]["tgt_norm_id"]:
            can_sua.append({**r, "tgt_norm_id": tn[0]["tgt_norm_id"]})
    print(f"  Còn da_duyet=true (chưa xử lý): {len(can_sua)}")

    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_path = f"_backup_reaudit_thi_hanh_{ts}.jsonl"
    with open(backup_path, "w", encoding="utf-8") as f:
        for r in can_sua:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  Đã ghi backup: {backup_path}")

    bat_dong_path = f"_bat_dong_reaudit_thi_hanh_{ts}.jsonl"
    with open(bat_dong_path, "w", encoding="utf-8") as f:
        for r in bat_dong:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  Đã ghi hàng chờ bất đồng: {bat_dong_path}")

    if not apply:
        print("\n== DRY RUN — chưa ghi gì. Chạy lại với --apply để thực thi. ==")
        return

    print("\n== Bước 2: revoke + mở lại Expression ==")
    tgt_norm_ids: set[str] = set()
    expr_ids_mo_lai: list[str] = []
    for i, r in enumerate(can_sua):
        neo.run(_Q_REVOKE, aid=r["action_id"],
               ghi_chu=f"REAUDIT_THI_HANH: re-audit voi ngu canh dung (Can cu + Dieu khoan thi hanh), "
                       f"2 model dong thuan {r['loai_deepseek']} (graph cu {r['loai_hien_tai_graph']})")
        mo_rows = neo.run(_Q_MO_LAI, aid=r["action_id"])
        expr_ids_mo_lai.extend(row["expr_id"] for row in mo_rows if row["expr_id"])
        tgt_norm_ids.add(r["tgt_norm_id"])
        if (i + 1) % 500 == 0:
            print(f"  {i+1}/{len(can_sua)} đã xử lý")
    print(f"  Đã revoke {len(can_sua)} cạnh, mở lại {len(expr_ids_mo_lai)} Expression, "
         f"ảnh hưởng {len(tgt_norm_ids)} Norm")

    print("== Bước 3: tính lại tinh_trang ==")
    today = date.today()
    dem_tt: dict[str, int] = {}
    for i, nid in enumerate(sorted(tgt_norm_ids)):
        states = [(r["tu"], r["den"]) for r in neo.run(_Q_STATES, nid=nid)]
        tt = str(derive_tinh_trang(states, today))
        if tt == "HetHieuLuc":
            neo.run("MATCH (n:Norm {norm_id:$nid}) SET n.tinh_trang=$tt", nid=nid, tt=tt)
        else:
            neo.run("MATCH (n:Norm {norm_id:$nid}) SET n.tinh_trang=$tt, n.eff_to=null", nid=nid, tt=tt)
        dem_tt[tt] = dem_tt.get(tt, 0) + 1
        if (i + 1) % 500 == 0:
            print(f"  {i+1}/{len(tgt_norm_ids)} Norm đã tính lại")
    print(f"  Kết quả tinh_trang: {dem_tt}")

    print("== Bước 4: đồng bộ Qdrant ==")
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
