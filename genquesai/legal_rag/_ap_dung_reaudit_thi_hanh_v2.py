"""Áp dụng kết quả re-audit "Điều khoản thi hành" — SỬA LẠI logic so với v1: các cạnh
trong nhóm A/B/C đều đã bị REVOKE từ trước (do rule cũ dùng ngữ cảnh thiếu bug) nên
da_duyet hiện tại đã là false — kiểm tra "còn da_duyet=true" trong v1 sai hoàn toàn (0
kết quả). Bản này xử lý đúng 2 tình huống:

  1. Verdict mới = KhongLienQuan -> khớp với trạng thái đã revoke sẵn -> KHÔNG CẦN LÀM GÌ
     (revoke cũ đã đúng, không phải "khác graph" theo nghĩa cần sửa).
  2. Verdict mới = 1 loại THẬT (ThayThe/BaiBoToanBo/SuaDoi/BaiBoTungPhan) -> revoke cũ SAI,
     cần KHÔI PHỤC: set lại loai + da_duyet=true + reset da_dong_hieu_luc=false, rồi ĐÓNG
     LẠI hiệu lực đúng cách (toàn bộ Norm cho ThayThe/BaiBoToanBo, đúng Component cho
     SuaDoi/BaiBoTungPhan — y hệt logic _dong_hieu_luc_da_duyet.py nhưng chạy TRỰC TIẾP
     cho từng action_id cụ thể, không quét hàng loạt).

Chạy: cd genquesai/legal_rag && python _ap_dung_reaudit_thi_hanh_v2.py [--apply]
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
TOAN_BO = {"ThayThe", "BaiBoToanBo"}
TUNG_PHAN = {"SuaDoi", "BaiBoTungPhan"}

_Q_AFFECTS = """
MATCH (a:Action {action_id:$aid})-[:AFFECTS]->(tgt)
RETURN labels(tgt) AS labels, coalesce(tgt.norm_id, tgt.comp_id) AS tgt_id
"""
_Q_SRC_NGAY_HL = "MATCH (a:Action {action_id:$aid})-[:ENACTED_BY]->(src:Norm) RETURN src.ngay_hieu_luc AS ngay_hieu_luc"
_Q_DA_DUYET = "MATCH (a:Action {action_id:$aid}) RETURN a.da_duyet AS da_duyet, a.loai AS loai"

_Q_KHONGLIENQUAN_XAC_NHAN = "MATCH (a:Action {action_id:$aid}) SET a.de_xuat_loai_2llm=$ghi_chu"

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


def doc_ung_vien() -> tuple[list[dict], list[dict]]:
    xac_nhan_dung, can_khoi_phuc = [], []
    with open(LOG_PATH, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("loi"):
                continue
            for r in d["ket_qua"]:
                ds, gm = r["loai_deepseek"], r["loai_gemini"]
                if ds is None or gm is None or not r["dong_thuan_2_model"]:
                    continue
                if ds == "KhongLienQuan":
                    xac_nhan_dung.append({**r, "norm_id": d["norm_id"]})
                else:
                    can_khoi_phuc.append({**r, "norm_id": d["norm_id"], "loai_moi": ds})
    return xac_nhan_dung, can_khoi_phuc


def main(apply: bool = False) -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    print("== Bước 1: phân loại theo verdict mới ==")
    xac_nhan_dung, can_khoi_phuc = doc_ung_vien()
    print(f"  Verdict=KhongLienQuan (khớp trạng thái đã revoke sẵn, không cần làm gì): {len(xac_nhan_dung)}")
    print(f"  Verdict=loại thật (revoke cũ SAI, cần khôi phục): {len(can_khoi_phuc)}")

    da_duyet_true, khong_ton_tai = 0, 0
    thuc_su_can_khoi_phuc = []
    for r in can_khoi_phuc:
        rows = neo.run(_Q_DA_DUYET, aid=r["action_id"])
        if not rows:
            khong_ton_tai += 1
            continue
        if rows[0]["da_duyet"] is True:
            da_duyet_true += 1
            continue
        thuc_su_can_khoi_phuc.append(r)
    print(f"  Trong đó đã da_duyet=true sẵn (không cần đụng): {da_duyet_true}")
    print(f"  Action không tồn tại (bất thường): {khong_ton_tai}")
    print(f"  THỰC SỰ cần khôi phục: {len(thuc_su_can_khoi_phuc)}")

    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_path = f"_backup_khoi_phuc_thi_hanh_{ts}.jsonl"
    with open(backup_path, "w", encoding="utf-8") as f:
        for r in thuc_su_can_khoi_phuc:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  Đã ghi backup: {backup_path}")

    if not apply:
        print("\n== DRY RUN — chưa ghi gì. Chạy lại với --apply để thực thi. ==")
        return

    print("\n== Bước 2: xác nhận lại các ca KhongLienQuan (chỉ cập nhật ghi chú) ==")
    for i, r in enumerate(xac_nhan_dung):
        neo.run(_Q_KHONGLIENQUAN_XAC_NHAN, aid=r["action_id"],
               ghi_chu="REAUDIT_THI_HANH_XAC_NHAN: re-audit ngu canh dung xac nhan KhongLienQuan, revoke truoc do dung")
        if (i + 1) % 1000 == 0:
            print(f"  {i+1}/{len(xac_nhan_dung)}")

    print("\n== Bước 3: khôi phục các cạnh bị revoke sai ==")
    tgt_norm_ids: set[str] = set()
    loi = 0
    for i, r in enumerate(thuc_su_can_khoi_phuc):
        aid = r["action_id"]
        aff = neo.run(_Q_AFFECTS, aid=aid)
        if not aff:
            loi += 1
            continue
        is_norm = "Norm" in aff[0]["labels"]
        ghi_chu = (f"REAUDIT_THI_HANH_KHOI_PHUC: revoke truoc do SAI (dua tren ngu canh thieu 84% noi dung), "
                  f"re-audit dong thuan {r['loai_moi']} - {r.get('ly_do_deepseek','')[:200]}")
        if r["loai_moi"] in TOAN_BO and is_norm:
            res = neo.run(_Q_KHOI_PHUC_TOANBO, aid=aid, loai_moi=r["loai_moi"], ghi_chu=ghi_chu)
        elif r["loai_moi"] in TUNG_PHAN and not is_norm:
            res = neo.run(_Q_KHOI_PHUC_TUNGPHAN, aid=aid, loai_moi=r["loai_moi"], ghi_chu=ghi_chu)
        else:
            # Loai moi khong khop kieu target hien co (vd verdict la SuaDoi nhung AFFECTS
            # dang tro Norm) -> KHONG tu y doi AFFECTS, chi khoi phuc da_duyet + loai, danh
            # dau can ra tay rieng thay vi tu dong dong sai pham vi.
            neo.run("MATCH (a:Action {action_id:$aid}) SET a.loai=$loai_moi, a.da_duyet=true, "
                   "a.de_xuat_loai_2llm=$ghi_chu",
                   aid=aid, loai_moi=r["loai_moi"],
                   ghi_chu=ghi_chu + " [CAN RA TAY: loai moi khac kieu target hien co, chua tu dong dong hieu luc]")
            loi += 1
            continue
        for row in res:
            if row["tgt_norm_id"]:
                tgt_norm_ids.add(row["tgt_norm_id"])
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(thuc_su_can_khoi_phuc)} đã xử lý")
    print(f"  Đã khôi phục {len(thuc_su_can_khoi_phuc) - loi} cạnh, {loi} ca cần rà tay riêng "
         f"(loại mới khác kiểu target hiện có), ảnh hưởng {len(tgt_norm_ids)} Norm")

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

    print("== Bước 5: đồng bộ Qdrant (set lại hieu_luc_den cho các Expression vừa đóng) ==")
    from qdrant_client import QdrantClient
    from qdrant_client import models as qm
    q = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None,
                     timeout=s.qdrant_timeout, check_compatibility=False)
    theo_ngay: dict[str, list[str]] = {}
    for r in thuc_su_can_khoi_phuc:
        rows = neo.run("MATCH (e:Expression {action_dong:$aid}) RETURN e.expr_id AS eid, e.hieu_luc_den AS hld",
                       aid=r["action_id"])
        for row in rows:
            if row["hld"]:
                theo_ngay.setdefault(str(row["hld"]), []).append(row["eid"])
    tong_diem = sum(len(v) for v in theo_ngay.values())
    print(f"  {tong_diem} điểm cần set lại hieu_luc_den trên Qdrant ({len(theo_ngay)} nhóm theo ngày)")
    CHUNK = 500
    da_xong = 0
    for hld, eids in theo_ngay.items():
        for i in range(0, len(eids), CHUNK):
            batch = eids[i:i + CHUNK]
            q.set_payload(s.qdrant_collection, payload={"hieu_luc_den": hld},
                         points=qm.Filter(must=[qm.FieldCondition(key="expr_id", match=qm.MatchAny(any=batch))]),
                         wait=True)
            da_xong += len(batch)
    print(f"  Đã đồng bộ {da_xong} điểm Qdrant")
    print(f"\n=== XONG. Backup tại {backup_path}. ===")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
