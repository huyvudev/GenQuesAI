"""Áp dụng verdict đọc tay TOÀN BỘ 151 ca còn lại của nhóm "khác nhóm" (toàn bộ vs
từng phần) — đọc trực tiếp (không qua fork, do fork không khả dụng trong worker này)
qua 2 file _verdict_khac_nhom_v2_phan{1,2}.jsonl.

Cùng cơ chế các lần trước: verdict xác định (1 trong 4 loại hợp lệ) VÀ khác graph hiện
tại -> revoke + reopen + recompute + sync. VBHN_KHONG_HOP_LE cũng revoke (mở rộng rule
VBHN). KHONG_RO -> để nguyên.

Chạy: cd genquesai/legal_rag && python _ap_dung_verdict_khac_nhom_v2.py [--apply]
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

KET_QUA_PATH = "_rasoat_2llm_deploy/rasoat_2llm_log_KETQUA.jsonl"
RETRY_PATH = "_retry_null_api_batched_log.jsonl"
VERDICT_PATHS = ["_verdict_khac_nhom_v2_phan1.jsonl", "_verdict_khac_nhom_v2_phan2.jsonl"]

TOAN_BO = {"ThayThe", "BaiBoToanBo"}
TUNG_PHAN = {"SuaDoi", "BaiBoTungPhan"}
LOAI_HOP_LE = {"ThayThe", "BaiBoToanBo", "SuaDoi", "BaiBoTungPhan"}

_Q_LOAI_VB_NGUON = "MATCH (n:Norm {norm_id:$nid}) RETURN n.loai_vb AS loai_vb"
_Q_TARGET_NORM = """
MATCH (a:Action {action_id:$aid})-[:AFFECTS]->(tgt)
OPTIONAL MATCH (tgt)<-[:HAS_PART*0..]-(pn:Norm)
RETURN coalesce(CASE WHEN 'Norm' IN labels(tgt) THEN tgt.norm_id ELSE null END, pn.norm_id) AS tgt_norm_id
"""
_Q_MO_LAI = "MATCH (e:Expression {action_dong:$aid}) SET e.hieu_luc_den=null, e.action_dong=null RETURN e.expr_id AS expr_id"
_Q_REVOKE = "MATCH (a:Action {action_id:$aid}) SET a.da_duyet=false, a.de_xuat_loai_2llm=$ghi_chu"
_Q_STATES = "MATCH (n:Norm {norm_id:$nid})-[:HAS_PART*]->(:Component)-[:HAS_VERSION]->(e:Expression) RETURN e.hieu_luc_tu AS tu, e.hieu_luc_den AS den"
_Q_DA_DUYET = "MATCH (a:Action {action_id:$aid}) RETURN a.da_duyet AS da_duyet"


def gom_ung_vien_khac_nhom() -> dict[str, dict]:
    def gom_sac_thai():
        out = []
        with open(KET_QUA_PATH, encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                if "ket_qua" not in d:
                    continue
                for r in d["ket_qua"]:
                    if r["dong_thuan_2_model"]:
                        continue
                    ds, gm = r["loai_deepseek"], r["loai_gemini"]
                    if ds and gm and ds != gm and ds != "KhongLienQuan" and gm != "KhongLienQuan":
                        out.append({**r, "norm_id": d["norm_id"]})
        with open(RETRY_PATH, encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                if d.get("loi"):
                    continue
                for r in d["ket_qua"]:
                    ds, gm = r["loai_deepseek"], r["loai_gemini"]
                    if ds and gm and ds != gm and ds != "KhongLienQuan" and gm != "KhongLienQuan":
                        out.append({**r, "norm_id": d["norm_id"]})
        return out

    ung_vien = gom_sac_thai()
    ket_qua = {}
    for r in ung_vien:
        ds, gm = r["loai_deepseek"], r["loai_gemini"]
        is_khac = (ds in TOAN_BO and gm in TUNG_PHAN) or (ds in TUNG_PHAN and gm in TOAN_BO)
        if is_khac:
            ket_qua[r["action_id"]] = r
    return ket_qua


def main(apply: bool = False) -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    print("== Bước 1: tái tạo danh sách ca gốc + đọc verdict 2 file ==")
    candidates = gom_ung_vien_khac_nhom()
    print(f"  {len(candidates)} ca gốc (toàn bộ nhóm khác nhóm, mọi thời điểm)")

    verdicts = {}
    for p in VERDICT_PATHS:
        with open(p, encoding="utf-8") as f:
            for line in f:
                v = json.loads(line)
                verdicts[v["action_id"]] = v
    print(f"  {len(verdicts)} verdict đọc được")

    khop = sum(1 for aid in verdicts if aid in candidates)
    print(f"  Khớp với danh sách gốc: {khop}/{len(verdicts)}")

    print("\n== Bước 2: phân loại hành động ==")
    can_sua_verdict = []
    can_sua_vbhn = []
    khong_can_sua = 0
    da_bi_dung_toi = 0
    khong_lam_gi = 0
    cache_loai_vb: dict[str, str] = {}

    for aid, v in verdicts.items():
        r = candidates.get(aid)
        if not r:
            continue
        rows = neo.run(_Q_DA_DUYET, aid=aid)
        if not (rows and rows[0]["da_duyet"] is True):
            da_bi_dung_toi += 1
            continue

        loai_dung = v["loai_dung"]
        if loai_dung in LOAI_HOP_LE:
            if loai_dung == r["loai_hien_tai_graph"]:
                khong_can_sua += 1
                continue
            tn = neo.run(_Q_TARGET_NORM, aid=aid)
            if tn and tn[0]["tgt_norm_id"]:
                can_sua_verdict.append({**r, "action_id": aid, "loai_dung": loai_dung,
                                        "ghi_chu_verdict": v.get("ghi_chu", ""),
                                        "tgt_norm_id": tn[0]["tgt_norm_id"]})
        elif loai_dung == "VBHN_KHONG_HOP_LE":
            tn = neo.run(_Q_TARGET_NORM, aid=aid)
            if tn and tn[0]["tgt_norm_id"]:
                can_sua_vbhn.append({**r, "action_id": aid, "ghi_chu_verdict": v.get("ghi_chu", ""),
                                     "tgt_norm_id": tn[0]["tgt_norm_id"]})
        else:  # KHONG_RO
            khong_lam_gi += 1

    print(f"  Verdict xác định, khác graph -> cần sửa: {len(can_sua_verdict)}")
    print(f"  VBHN không hợp lệ -> cần sửa: {len(can_sua_vbhn)}")
    print(f"  Verdict khớp sẵn graph, không cần sửa: {khong_can_sua}")
    print(f"  Đã bị rule khác đụng tới trước đó: {da_bi_dung_toi}")
    print(f"  KHONG_RO -> để nguyên: {khong_lam_gi}")

    tat_ca_can_sua = can_sua_verdict + can_sua_vbhn
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_path = f"_backup_khac_nhom_v2_doctay_{ts}.jsonl"
    with open(backup_path, "w", encoding="utf-8") as f:
        for r in tat_ca_can_sua:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  Đã ghi backup: {backup_path}")

    if not apply:
        print("\n== DRY RUN — chưa ghi gì. Chạy lại với --apply để thực thi. ==")
        return

    print("\n== Bước 3: revoke + mở lại Expression ==")
    tgt_norm_ids: set[str] = set()
    expr_ids_mo_lai: list[str] = []
    for i, r in enumerate(tat_ca_can_sua):
        if "loai_dung" in r:
            ghi_chu = f"KHAC_NHOM_V2_DOC_TAY: doc tay xac nhan loai dung la {r['loai_dung']} (graph hien tai {r['loai_hien_tai_graph']}) - {r['ghi_chu_verdict']}"
        else:
            ghi_chu = f"KHAC_NHOM_V2_VBHN: nguon la VBHN, khong hop le - {r['ghi_chu_verdict']}"
        neo.run(_Q_REVOKE, aid=r["action_id"], ghi_chu=ghi_chu)
        mo_rows = neo.run(_Q_MO_LAI, aid=r["action_id"])
        expr_ids_mo_lai.extend(row["expr_id"] for row in mo_rows if row["expr_id"])
        tgt_norm_ids.add(r["tgt_norm_id"])
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(tat_ca_can_sua)} đã xử lý")
    print(f"  Đã revoke {len(tat_ca_can_sua)} cạnh, mở lại {len(expr_ids_mo_lai)} Expression, "
         f"ảnh hưởng {len(tgt_norm_ids)} Norm")

    print("== Bước 4: tính lại tinh_trang ==")
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

    print("== Bước 5: đồng bộ Qdrant ==")
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
