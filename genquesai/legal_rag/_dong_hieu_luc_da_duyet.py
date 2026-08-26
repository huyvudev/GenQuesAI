"""Dong hieu luc THAT cho cac Action da_duyet=true — buoc con thieu sau khi duyet
(da_duyet=true chi la co da REVIEW, KHONG tu dong dong hieu luc VB/Dieu bi tac dong).

2 nhom xu ly:
1. REPLACES-type (loai ThayThe hoac BaiBoToanBo, thay the/bai bo TOAN BO VB dich):
   dong TAT CA Expression con mo cua VB dich, tai ngay hieu luc cua VB nguon. Mo rong
   tu `close_replaced` trong reconcile.py (truoc chi xu ly rieng ThayThe qua tung
   action_id) — o day xu ly HANG LOAT ca 2 loai, dong thoi set tinh_trang='HetHieuLuc'.

2. AMENDS-type DA CO CAP DIEU CU THE (loai SuaDoi/BaiBoTungPhan, AFFECTS tro toi
   Component chu khong phai Norm — sau buoc _trich_cap_dieu.py): CHI dong Expression
   cua dung Component do (KHONG dong ca Van Ban — chi 1 Dieu/Khoan/Diem bi sua/bai bo).

KHONG xu ly: AMENDS con o cap "Ca van ban" (AFFECTS -> Norm truc tiep, chua tach
duoc Dieu cu the) — day la quyet dinh CAN NGUOI DUNG XAC NHAN truoc (dong ca VB thi
qua manh vi chi la sua 1 phan, khong dong thi VB do "lo lung" khong phan anh dung
tinh trang) — script nay in ra so luong de bao cao, KHONG tu dong xu ly."""
from __future__ import annotations
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")
from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient

_Q_CLOSE_REPLACES = """
MATCH (a:Action)-[:ENACTED_BY]->(src:Norm)
WHERE coalesce(a.da_duyet,false)=true AND a.loai IN ['ThayThe','BaiBoToanBo']
      AND src.ngay_hieu_luc IS NOT NULL AND coalesce(a.da_dong_hieu_luc,false)=false
WITH a, src LIMIT $batch
MATCH (a)-[:AFFECTS]->(tgt)
MATCH (tgtn:Norm {norm_id: tgt.norm_id})
OPTIONAL MATCH (tgtn)-[:HAS_PART*]->(:Component)-[:HAS_VERSION]->(e:Expression)
  WHERE e.hieu_luc_den IS NULL
FOREACH (_ IN CASE WHEN e IS NOT NULL THEN [1] ELSE [] END |
  SET e.hieu_luc_den = src.ngay_hieu_luc, e.action_dong = a.action_id)
WITH a, tgtn, src, count(e) AS n_closed
SET tgtn.tinh_trang = 'HetHieuLuc', tgtn.eff_to = src.ngay_hieu_luc, a.da_dong_hieu_luc = true
RETURN count(DISTINCT a) AS actions, sum(n_closed) AS expressions
"""

_Q_CLOSE_AMENDS_COMPONENT = """
MATCH (a:Action)-[:ENACTED_BY]->(src:Norm)
WHERE coalesce(a.da_duyet,false)=true AND a.loai IN ['SuaDoi','BaiBoTungPhan']
      AND src.ngay_hieu_luc IS NOT NULL AND coalesce(a.da_dong_hieu_luc,false)=false
      AND EXISTS { MATCH (a)-[:AFFECTS]->(:Component) }
WITH a, src LIMIT $batch
MATCH (a)-[:AFFECTS]->(c:Component)
OPTIONAL MATCH (c)-[:HAS_VERSION]->(e:Expression)
  WHERE e.hieu_luc_den IS NULL
FOREACH (_ IN CASE WHEN e IS NOT NULL THEN [1] ELSE [] END |
  SET e.hieu_luc_den = src.ngay_hieu_luc, e.action_dong = a.action_id)
WITH a, count(e) AS n_closed
SET a.da_dong_hieu_luc = true
RETURN count(DISTINCT a) AS actions, sum(n_closed) AS expressions
"""

_Q_AMENDS_CA_VAN_BAN_CHUA_XU_LY = """
MATCH (a:Action)-[:AFFECTS]->(tgt:Norm)
WHERE coalesce(a.da_duyet,false)=true AND a.loai IN ['SuaDoi','BaiBoTungPhan']
RETURN count(a) AS n
"""


def main() -> None:
    s = get_settings()
    s_local = s.model_copy(update={
        "neo4j_uri": "bolt://localhost:7687", "neo4j_user": "neo4j",
        "neo4j_password": "123qwe", "neo4j_database": "neo4j",
    })
    neo = Neo4jClient(s_local)
    neo.verify()

    print("== 1. Đóng hiệu lực REPLACES-type (ThayThe + BaiBoToanBo) ==")
    tong_a, tong_e = 0, 0
    while True:
        r = neo.run(_Q_CLOSE_REPLACES, batch=300)[0]
        n_a, n_e = r["actions"] or 0, r["expressions"] or 0
        tong_a += n_a
        tong_e += n_e
        if n_a == 0:
            break
        print(f"  ...lô: {n_a} action, {n_e} expression đóng (cộng dồn {tong_a:,}/{tong_e:,})")
    print(f"  TỔNG: Action xử lý: {tong_a:,} | Expression đóng: {tong_e:,}")

    print("== 2. Đóng hiệu lực AMENDS-type ĐÃ CÓ cấp Điều/Khoản/Điểm cụ thể ==")
    tong_a2, tong_e2 = 0, 0
    while True:
        r = neo.run(_Q_CLOSE_AMENDS_COMPONENT, batch=300)[0]
        n_a, n_e = r["actions"] or 0, r["expressions"] or 0
        tong_a2 += n_a
        tong_e2 += n_e
        if n_a == 0:
            break
        print(f"  ...lô: {n_a} action, {n_e} expression đóng (cộng dồn {tong_a2:,}/{tong_e2:,})")
    print(f"  TỔNG: Action xử lý: {tong_a2:,} | Expression đóng: {tong_e2:,}")

    r3 = neo.run(_Q_AMENDS_CA_VAN_BAN_CHUA_XU_LY)[0]
    print(f"== CHƯA xử lý: {r3['n']:,} cạnh AMENDS đã duyệt nhưng còn ở cấp 'Cả văn bản' "
          f"(AFFECTS -> Norm trực tiếp) — cần quyết định trước khi đóng hiệu lực. ==")


if __name__ == "__main__":
    main()
