"""Bước 2 (sau khi rà soát 2 LLM, 2026-09-08) — áp dụng rule tự động cho 1 phần nhóm
BẤT ĐỒNG "có quan hệ thật hay không" (1 bên nói ThayThe/SuaDoi/BaiBoToanBo/
BaiBoTungPhan, bên kia nói KhongLienQuan): nếu văn bản NGUỒN và ĐÍCH có
`co_quan_ban_hanh` KHÁC HẲN nhau, gần như chắc chắn là **match nhầm số hiệu trùng
giữa các địa phương** (đã xác nhận qua đọc mẫu thật — vd Quyết định 45/2014/QĐ-UBND
của tỉnh Hà Nam bị match nhầm với 45/2014/QĐ-UBND của tỉnh Thừa Thiên Huế — số hiệu
văn bản địa phương KHÔNG duy nhất toàn quốc).

Quy tắc: cơ quan khác hẳn -> TIN bên nói "KhongLienQuan" là đúng -> áp dụng ĐÚNG cơ
chế đã dùng cho nhóm "đồng thuận cao" (`_sua_dong_thuan_2llm.py`): revoke da_duyet +
mở lại Expression bị đóng sai + tính lại tinh_trang + đồng bộ Qdrant. KHÔNG xoá cạnh,
chỉ đưa về hàng đợi cần rà tay.

Chạy: cd genquesai/legal_rag && python ../../_sua_bat_dong_co_quan_khac.py [--apply]
(mặc định dry-run)."""
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

_Q_CO_QUAN = """
MATCH (src:Norm {norm_id:$nid})
MATCH (a:Action {action_id:$aid})-[:AFFECTS]->(tgt)
OPTIONAL MATCH (tgt)<-[:HAS_PART*0..]-(pn:Norm)
WITH src, coalesce(CASE WHEN 'Norm' IN labels(tgt) THEN tgt ELSE null END, pn) AS tgtn
RETURN src.co_quan_ban_hanh AS src_cq, tgtn.co_quan_ban_hanh AS tgt_cq,
       tgtn.norm_id AS tgt_norm_id
"""

_Q_MO_LAI = "MATCH (e:Expression {action_dong:$aid}) SET e.hieu_luc_den=null, e.action_dong=null RETURN e.expr_id AS expr_id"
_Q_REVOKE = "MATCH (a:Action {action_id:$aid}) SET a.da_duyet=false, a.de_xuat_loai_2llm=$ghi_chu"
_Q_STATES = "MATCH (n:Norm {norm_id:$nid})-[:HAS_PART*]->(:Component)-[:HAS_VERSION]->(e:Expression) RETURN e.hieu_luc_tu AS tu, e.hieu_luc_den AS den"


def doc_danh_sach_bat_dong() -> list[dict]:
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
                if ds and gm and "KhongLienQuan" in (ds, gm):
                    ket_qua.append({**r, "norm_id": d["norm_id"], "vb_nguon": d["so_hieu"]})
    return ket_qua


def main(apply: bool = False) -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    print("== Bước 1: đọc nhóm bất đồng 'có thật/KhongLienQuan' + kiểm tra cơ quan ban hành ==")
    ung_vien = doc_danh_sach_bat_dong()
    print(f"  {len(ung_vien)} cạnh trong nhóm này")

    can_sua = []
    for i, r in enumerate(ung_vien):
        rows = neo.run(_Q_CO_QUAN, nid=r["norm_id"], aid=r["action_id"])
        if not rows:
            continue
        src_cq, tgt_cq, tgt_nid = rows[0]["src_cq"], rows[0]["tgt_cq"], rows[0]["tgt_norm_id"]
        if not src_cq or not tgt_cq or not tgt_nid:
            continue
        if src_cq.strip().lower() != tgt_cq.strip().lower():
            loai_that = r["loai_gemini"] if r["loai_deepseek"] == "KhongLienQuan" else r["loai_deepseek"]
            can_sua.append({**r, "tgt_norm_id": tgt_nid, "loai_bi_nghi_sai": loai_that,
                            "src_cq": src_cq, "tgt_cq": tgt_cq})
        if (i + 1) % 1000 == 0:
            print(f"  {i+1}/{len(ung_vien)} đã kiểm tra, tìm được {len(can_sua)} ca cơ quan khác nhau")

    print(f"\n  KẾT QUẢ: {len(can_sua)}/{len(ung_vien)} cạnh có cơ quan ban hành khác hẳn nhau")

    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_path = f"_backup_bat_dong_co_quan_khac_{ts}.jsonl"
    with open(backup_path, "w", encoding="utf-8") as f:
        for r in can_sua:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  Đã ghi backup: {backup_path}")

    if not apply:
        print("\n== DRY RUN — chưa ghi gì. Chạy lại với --apply để thực thi. ==")
        return

    print("\n== Bước 2: revoke da_duyet + mở lại Expression ==")
    tgt_norm_ids: set[str] = set()
    expr_ids_mo_lai: list[str] = []
    for i, r in enumerate(can_sua):
        ghi_chu = (f"NGHI_MATCH_NHAM_SO_HIEU: co_quan nguon='{r['src_cq']}' khac dich='{r['tgt_cq']}' "
                  f"-- loai that co the la={r['loai_bi_nghi_sai']} (neu dich dung)")
        neo.run(_Q_REVOKE, aid=r["action_id"], ghi_chu=ghi_chu)
        mo_rows = neo.run(_Q_MO_LAI, aid=r["action_id"])
        expr_ids_mo_lai.extend(row["expr_id"] for row in mo_rows if row["expr_id"])
        tgt_norm_ids.add(r["tgt_norm_id"])
        if (i + 1) % 500 == 0:
            print(f"  {i+1}/{len(can_sua)} cạnh đã xử lý")
    print(f"  Đã revoke {len(can_sua)} cạnh, mở lại {len(expr_ids_mo_lai)} Expression, "
         f"ảnh hưởng {len(tgt_norm_ids)} Norm đích")

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
