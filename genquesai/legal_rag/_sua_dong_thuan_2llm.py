"""Áp dụng sửa cho nhóm "đồng thuận cao" từ đợt rà soát 2 LLM (2026-09-05/08,
`_rasoat_2llm_deploy/rasoat_2llm.py`) — 16.671 cạnh mà DeepSeek + Gemini ĐỘC LẬP cùng
đồng ý phân loại KHÁC với nhãn hiện có trong graph (`dong_thuan_2_model=true` VÀ
`khac_voi_graph=true`).

QUYẾT ĐỊNH THIẾT KẾ (nhất quán với cách đã làm hôm 2026-09-05 cho 397 cạnh — xem
_sua_253_canh_thay_the_sai.py): KHÔNG tự động ghi đè `Action.loai` thành giá trị mới
2 model đề xuất — vì việc đó có thể cần thêm bước resolve cấp Điều (nếu đổi từ
ThayThe/BaiBoToanBo sang SuaDoi/BaiBoTungPhan, đích cần trỏ đúng Component chứ không
phải cả Norm) mà đợt rà soát này chưa làm. Thay vào đó:
1. REVOKE `da_duyet=false` — đưa về hàng đợi cần rà tay (không tự ý coi là đã duyệt).
2. Ghi chú `de_xuat_loai_2llm` = phân loại 2 model đề xuất, để người rà tham khảo.
3. MỞ LẠI mọi Expression đã bị đóng sai do đúng cạnh này (`action_dong` khớp) — đây
   là phần AN TOÀN để tự động, vì nếu graph SAI (2 model đồng thuận nói vậy), việc
   đóng hiệu lực theo cạnh sai đó chắc chắn cũng sai, cần mở lại ngay (giống hệt lý do
   bug 397 cạnh ảnh hưởng retrieval thật hôm 2026-09-05).
4. Tính lại `tinh_trang` cho Norm đích bị ảnh hưởng.
5. Đồng bộ Qdrant (xoá payload `hieu_luc_den` cũ).

Backup TRƯỚC khi ghi — xem `_backup_dong_thuan_2llm_*.jsonl`.

Chạy: cd genquesai/legal_rag && python ../../_sua_dong_thuan_2llm.py [--apply]
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

_Q_TARGET_NORM = """
MATCH (a:Action {action_id:$aid})-[:AFFECTS]->(tgt)
OPTIONAL MATCH (tgt)<-[:HAS_PART*0..]-(pn:Norm)
RETURN coalesce(
  CASE WHEN 'Norm' IN labels(tgt) THEN tgt.norm_id ELSE null END,
  pn.norm_id
) AS tgt_norm_id
"""

_Q_MO_LAI = "MATCH (e:Expression {action_dong:$aid}) SET e.hieu_luc_den=null, e.action_dong=null RETURN e.expr_id AS expr_id"
_Q_REVOKE = "MATCH (a:Action {action_id:$aid}) SET a.da_duyet=false, a.de_xuat_loai_2llm=$loai_moi"
_Q_STATES = "MATCH (n:Norm {norm_id:$nid})-[:HAS_PART*]->(:Component)-[:HAS_VERSION]->(e:Expression) RETURN e.hieu_luc_tu AS tu, e.hieu_luc_den AS den"
_Q_ACTION_HIEN_TAI = "MATCH (a:Action {action_id:$aid}) RETURN coalesce(a.da_duyet,false) AS da_duyet"


def doc_danh_sach_can_sua() -> list[dict]:
    ket_qua = []
    with open(KET_QUA_PATH, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if "ket_qua" not in d:
                continue
            for r in d["ket_qua"]:
                if r["dong_thuan_2_model"] and r["khac_voi_graph"]:
                    ket_qua.append({**r, "vb_nguon": d["so_hieu"]})
    return ket_qua


def main(apply: bool = False) -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    print("== Bước 1: đọc danh sách cạnh cần sửa từ kết quả rà soát 2 LLM ==")
    can_sua = doc_danh_sach_can_sua()
    print(f"  {len(can_sua)} cạnh (đồng thuận cao, khác graph hiện tại)")

    theo_loai_moi: dict[str, int] = {}
    for r in can_sua:
        theo_loai_moi[r["loai_deepseek"]] = theo_loai_moi.get(r["loai_deepseek"], 0) + 1
    print(f"  Chia theo phân loại 2 model đề xuất: {theo_loai_moi}")

    print("== Bước 2: BACKUP trạng thái trước khi sửa ==")
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_path = f"_backup_dong_thuan_2llm_{ts}.jsonl"
    backup_rows = []
    for r in can_sua:
        cur = neo.run(_Q_ACTION_HIEN_TAI, aid=r["action_id"])
        backup_rows.append({
            "action_id": r["action_id"], "loai_hien_tai_graph": r["loai_hien_tai_graph"],
            "loai_moi_de_xuat": r["loai_deepseek"], "da_duyet_truoc": cur[0]["da_duyet"] if cur else None,
        })
    with open(backup_path, "w", encoding="utf-8") as f:
        for row in backup_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  Đã ghi backup: {backup_path}")

    if not apply:
        print("\n== DRY RUN — chưa ghi gì. Chạy lại với --apply để thực thi. ==")
        return

    print("\n== Bước 3: revoke da_duyet + ghi đề xuất + mở lại Expression ==")
    tgt_norm_ids: set[str] = set()
    expr_ids_mo_lai: list[str] = []
    for i, r in enumerate(can_sua):
        neo.run(_Q_REVOKE, aid=r["action_id"], loai_moi=r["loai_deepseek"])
        mo_rows = neo.run(_Q_MO_LAI, aid=r["action_id"])
        expr_ids_mo_lai.extend(row["expr_id"] for row in mo_rows if row["expr_id"])
        tn = neo.run(_Q_TARGET_NORM, aid=r["action_id"])
        if tn and tn[0]["tgt_norm_id"]:
            tgt_norm_ids.add(tn[0]["tgt_norm_id"])
        if (i + 1) % 1000 == 0:
            print(f"  {i+1}/{len(can_sua)} cạnh đã xử lý")
    print(f"  Đã revoke {len(can_sua)} cạnh, mở lại {len(expr_ids_mo_lai)} Expression, "
         f"ảnh hưởng {len(tgt_norm_ids)} Norm đích")

    print("== Bước 4: tính lại tinh_trang cho từng Norm đích ==")
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
        print(f"  Đã xoá payload {min(i+CHUNK, len(expr_ids_mo_lai))}/{len(expr_ids_mo_lai)}")

    print(f"\n=== XONG. Backup tại {backup_path}. ===")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
