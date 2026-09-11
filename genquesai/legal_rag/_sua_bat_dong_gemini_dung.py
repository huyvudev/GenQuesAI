"""Áp dụng "tin Gemini" cho nhóm bất đồng "DeepSeek nói có quan hệ thật, Gemini nói
KhongLienQuan" — đã xác minh bằng đọc tay 30 mẫu ngẫu nhiên (2026-09-09): 17/30 đủ dữ
liệu phán quyết, 100% nghiêng về Gemini, 0% DeepSeek đúng (DeepSeek lộ 4 kiểu lỗi hệ
thống: suy diễn hành chính suông, copy lý do giữa nhiều đích, hedging tự lộ độ tin
thấp, đọc sai chính bằng chứng mình trích).

CHỈ áp dụng cho cạnh mà toàn văn nguồn đủ thực chất (>=500 ký tự không rỗng sau khi bỏ
khoảng trắng) — loại các nguồn gần như trống nội dung trong graph (43% mẫu đọc tay rơi
vào nhóm này, ở đó Gemini nói KhongLienQuan chỉ vì thiếu dữ liệu để đọc, không phải
phán quyết có căn cứ thật). Nhóm nguồn rỗng bị loại ra được ghi riêng để rà tay sau,
KHÔNG bulk-trust.

Loại trừ nguồn là VBHN (đã fix ở rule riêng _sua_bat_dong_vbhn.py).

Cùng cơ chế 4 rule trước: revoke da_duyet + mở lại Expression + tính lại tinh_trang +
đồng bộ Qdrant.

Chạy: cd genquesai/legal_rag && python _sua_bat_dong_gemini_dung.py [--apply]
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
NGUONG_KY_TU = 500

_Q_LOAI_VB_NGUON = "MATCH (n:Norm {norm_id:$nid}) RETURN n.loai_vb AS loai_vb"
_Q_TOAN_VAN = """
MATCH (n:Norm {norm_id:$nid})-[:HAS_PART*]->(d:Component)-[:HAS_VERSION]->(e:Expression)
WHERE d.loai IN ['Dieu','ToanVan']
RETURN e.text AS text
"""
_Q_TARGET_NORM = """
MATCH (a:Action {action_id:$aid})-[:AFFECTS]->(tgt)
OPTIONAL MATCH (tgt)<-[:HAS_PART*0..]-(pn:Norm)
RETURN coalesce(CASE WHEN 'Norm' IN labels(tgt) THEN tgt.norm_id ELSE null END, pn.norm_id) AS tgt_norm_id
"""
_Q_MO_LAI = "MATCH (e:Expression {action_dong:$aid}) SET e.hieu_luc_den=null, e.action_dong=null RETURN e.expr_id AS expr_id"
_Q_REVOKE = "MATCH (a:Action {action_id:$aid}) SET a.da_duyet=false, a.de_xuat_loai_2llm=$ghi_chu"
_Q_STATES = "MATCH (n:Norm {norm_id:$nid})-[:HAS_PART*]->(:Component)-[:HAS_VERSION]->(e:Expression) RETURN e.hieu_luc_tu AS tu, e.hieu_luc_den AS den"


def doc_ung_vien() -> list[dict]:
    ket_qua = []
    with open(KET_QUA_PATH, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if "ket_qua" not in d:
                continue
            for r in d["ket_qua"]:
                if r["dong_thuan_2_model"]:
                    continue
                ds, gm = r["loai_deepseek"], r["loai_gemini"]
                if ds and gm and ds != "KhongLienQuan" and gm == "KhongLienQuan":
                    ket_qua.append({**r, "norm_id": d["norm_id"], "so_hieu_nguon": d["so_hieu"]})
    return ket_qua


def _do_dai_khong_rong(s: str) -> int:
    return len("".join((s or "").split()))


def main(apply: bool = False) -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    print("== Bước 1: lọc nhóm bất đồng DeepSeek=có thật/Gemini=KhongLienQuan, loại VBHN ==")
    ung_vien = doc_ung_vien()
    print(f"  {len(ung_vien)} cạnh ứng viên (trước lọc VBHN + độ dài)")

    cache_loai_vb: dict[str, str] = {}
    cache_do_dai: dict[str, int] = {}
    can_sua, qua_mong = [], []
    for i, r in enumerate(ung_vien):
        nid = r["norm_id"]
        if nid not in cache_loai_vb:
            rows = neo.run(_Q_LOAI_VB_NGUON, nid=nid)
            cache_loai_vb[nid] = rows[0]["loai_vb"] if rows else None
        if cache_loai_vb[nid] == "VanBanHopNhat":
            continue
        if nid not in cache_do_dai:
            rows = neo.run(_Q_TOAN_VAN, nid=nid)
            cache_do_dai[nid] = sum(_do_dai_khong_rong(row["text"]) for row in rows)
        if cache_do_dai[nid] < NGUONG_KY_TU:
            qua_mong.append(r)
            continue
        tn = neo.run(_Q_TARGET_NORM, aid=r["action_id"])
        if tn and tn[0]["tgt_norm_id"]:
            can_sua.append({**r, "tgt_norm_id": tn[0]["tgt_norm_id"]})
        if (i + 1) % 500 == 0:
            print(f"  {i+1}/{len(ung_vien)} đã lọc")

    print(f"  Đủ điều kiện áp dụng (nguồn không phải VBHN, toàn văn >= {NGUONG_KY_TU} ký tự): {len(can_sua)}")
    print(f"  Loại ra vì nguồn quá mỏng (đưa vào hàng chờ rà tay riêng): {len(qua_mong)}")

    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_path = f"_backup_bat_dong_gemini_dung_{ts}.jsonl"
    with open(backup_path, "w", encoding="utf-8") as f:
        for r in can_sua:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  Đã ghi backup: {backup_path}")

    hang_cho_path = f"_hang_cho_ra_tay_nguon_mong_{ts}.jsonl"
    with open(hang_cho_path, "w", encoding="utf-8") as f:
        for r in qua_mong:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  Đã ghi hàng chờ rà tay (nguồn mỏng): {hang_cho_path}")

    if not apply:
        print("\n== DRY RUN — chưa ghi gì. Chạy lại với --apply để thực thi. ==")
        return

    print("== Bước 2: revoke + mở lại Expression ==")
    tgt_norm_ids: set[str] = set()
    expr_ids_mo_lai: list[str] = []
    for i, r in enumerate(can_sua):
        neo.run(_Q_REVOKE, aid=r["action_id"],
               ghi_chu="BAT_DONG_TIN_GEMINI: doc tay 30 mau xac nhan Gemini dung (17/17 co du lieu), "
                       "nguon du thuc chat (>=500 ky tu) nhung khong co can cu thuc su -> tin KhongLienQuan")
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
        print(f"  Đã xoá payload {min(i+CHUNK, len(expr_ids_mo_lai))}/{len(expr_ids_mo_lai)}")
    print(f"  Đã đồng bộ {len(expr_ids_mo_lai)} điểm Qdrant")
    print(f"\n=== XONG. Backup tại {backup_path}. Hàng chờ rà tay tại {hang_cho_path}. ===")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
