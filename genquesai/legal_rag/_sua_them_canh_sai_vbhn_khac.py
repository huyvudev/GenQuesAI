"""Mở rộng bug đã sửa (`_sua_253_canh_thay_the_sai.py`) — rule cấp bậc chỉ bắt được
1 phần. Thêm 2 rule mới, CẢ 2 ĐỀU chắc chắn sai bất kể cấp bậc:

1. src.loai_vb='VanBanHopNhat' — Văn bản hợp nhất CHỈ là bản tổng hợp tham khảo do
   Quốc hội/UBTVQH ban hành, KHÔNG PHẢI hành vi lập pháp mới -> không bao giờ hợp lệ
   để "thay thế/bãi bỏ toàn bộ" văn bản khác.
2. src.loai_vb='Khac' — kiểm tra mẫu 16 ca thấy TOÀN BỘ là công văn hành chính/sắc
   lệnh cũ, đích không liên quan chủ đề (vd "thành lập Sở mậu dịch" bị gắn "thay thế"
   "tội đánh bạc") — công văn không phải VBQPPL, không có hiệu lực "thay thế".

KHÔNG xử lý rule "cùng cấp bậc" tổng quát (11.722 cạnh, phần lớn HỢP LỆ — vd Bộ luật
Dân sự 2015 thay Bộ luật Dân sự 2005 là ĐÚNG) — cần cách nhận diện tinh vi hơn (so
khớp chủ đề), để làm riêng sau, KHÔNG blanket-fix ở đây.

Quy trình + script giống hệt bản trước: backup trước khi ghi, revoke da_duyet, mở
lại Expression, tính lại tinh_trang bằng derive_tinh_trang, đồng bộ Qdrant.

Chạy: cd genquesai/legal_rag && python _sua_them_canh_sai_vbhn_khac.py [--apply]"""
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

_Q_CANH_SAI = """
MATCH (a:Action)-[:ENACTED_BY]->(src:Norm)
MATCH (a)-[:AFFECTS]->(tgt:Norm)
WHERE coalesce(a.da_duyet,false)=true AND a.loai IN ['ThayThe','BaiBoToanBo']
  AND src.loai_vb IN ['VanBanHopNhat','Khac']
RETURN a.action_id AS action_id, a.loai AS loai, a.ngay_hieu_luc AS ngay_hieu_luc,
       src.so_hieu AS src_so_hieu, src.loai_vb AS src_loai_vb, src.cap_bac AS src_cap_bac,
       tgt.norm_id AS tgt_norm_id, tgt.so_hieu AS tgt_so_hieu, tgt.cap_bac AS tgt_cap_bac
"""

_Q_EXPR_BI_ANH_HUONG = """
MATCH (e:Expression) WHERE e.action_dong IN $action_ids
RETURN e.expr_id AS expr_id, e.comp_id AS comp_id, e.hieu_luc_tu AS hieu_luc_tu,
       e.hieu_luc_den AS hieu_luc_den, e.action_dong AS action_dong
"""

_Q_MO_LAI = """
MATCH (e:Expression) WHERE e.action_dong IN $action_ids
SET e.hieu_luc_den = null, e.action_dong = null
RETURN count(e) AS so_luong
"""

_Q_REVOKE_DUYET = """
MATCH (a:Action) WHERE a.action_id IN $action_ids
SET a.da_duyet = false
RETURN count(a) AS so_luong
"""

_Q_TRANG_THAI_NORM = """
MATCH (n:Norm {norm_id: $norm_id})-[:HAS_PART*]->(:Component)-[:HAS_VERSION]->(e:Expression)
RETURN e.hieu_luc_tu AS tu, e.hieu_luc_den AS den
"""


def main(apply: bool = False) -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    print("== Bước 1: xác định cạnh sai (nguồn VanBanHopNhat/Khac) ==")
    canh_sai = neo.run(_Q_CANH_SAI)
    print(f"  Tìm thấy {len(canh_sai)} cạnh")
    theo_loai: dict[str, int] = {}
    for r in canh_sai:
        theo_loai[r["src_loai_vb"]] = theo_loai.get(r["src_loai_vb"], 0) + 1
    print(f"  Chia theo loại nguồn: {theo_loai}")
    action_ids = [r["action_id"] for r in canh_sai]
    norm_ids_anh_huong = sorted({r["tgt_norm_id"] for r in canh_sai})
    print(f"  Ảnh hưởng {len(norm_ids_anh_huong)} Norm đích")

    print("== Bước 2: liệt kê Expression sẽ bị mở lại + BACKUP ==")
    expr_rows = neo.run(_Q_EXPR_BI_ANH_HUONG, action_ids=action_ids)
    print(f"  {len(expr_rows)} Expression sẽ được mở lại")

    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_path = f"_backup_vbhn_khac_sai_{ts}.jsonl"
    with open(backup_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"loai": "canh_sai", "rows": canh_sai}, ensure_ascii=False, default=str) + "\n")
        for r in expr_rows:
            f.write(json.dumps({"loai": "expression_truoc_khi_sua", **r}, ensure_ascii=False, default=str) + "\n")
    print(f"  Đã ghi backup: {backup_path}")

    if not apply:
        print("\n== DRY RUN — chưa ghi gì. Chạy lại với --apply để thực thi. ==")
        return

    print("\n== Bước 3: ghi vào Neo4j ==")
    r1 = neo.run(_Q_REVOKE_DUYET, action_ids=action_ids)
    print(f"  Revoke da_duyet: {r1[0]['so_luong']} Action")
    r2 = neo.run(_Q_MO_LAI, action_ids=action_ids)
    print(f"  Mở lại Expression: {r2[0]['so_luong']}")

    print("== Bước 4: tính lại tinh_trang cho từng Norm ảnh hưởng ==")
    today = date.today()
    dem_tt: dict[str, int] = {}
    for nid in norm_ids_anh_huong:
        states = [(r["tu"], r["den"]) for r in neo.run(_Q_TRANG_THAI_NORM, norm_id=nid)]
        tt = str(derive_tinh_trang(states, today))
        if tt == "HetHieuLuc":
            neo.run("MATCH (n:Norm {norm_id:$nid}) SET n.tinh_trang=$tt", nid=nid, tt=tt)
        else:
            neo.run("MATCH (n:Norm {norm_id:$nid}) SET n.tinh_trang=$tt, n.eff_to=null", nid=nid, tt=tt)
        dem_tt[tt] = dem_tt.get(tt, 0) + 1
    print(f"  Kết quả tinh_trang mới: {dem_tt}")

    print("== Bước 5: đồng bộ Qdrant ==")
    from qdrant_client import QdrantClient
    from qdrant_client import models as qm
    q = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None,
                     timeout=s.qdrant_timeout, check_compatibility=False)
    expr_ids = [r["expr_id"] for r in expr_rows if r["expr_id"]]
    CHUNK = 500
    tong_diem = 0
    for i in range(0, len(expr_ids), CHUNK):
        batch = expr_ids[i:i + CHUNK]
        q.delete_payload(
            s.qdrant_collection, keys=["hieu_luc_den"],
            points=qm.Filter(must=[qm.FieldCondition(key="expr_id", match=qm.MatchAny(any=batch))]),
            wait=True)
        tong_diem += len(batch)
        print(f"  Đã xoá payload cho {tong_diem}/{len(expr_ids)} expr_id")

    print(f"\n=== XONG. Backup tại {backup_path}. ===")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
