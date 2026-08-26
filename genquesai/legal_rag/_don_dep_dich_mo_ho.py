"""Don dep bug 'nhan doi dich' (2026-08-25): 25.572 Action bi MERGE toi NHIEU Norm
cung so_hieu (1.247 so_hieu trung giua cac Norm khac nhau trong graph). Xoa cac canh
AFFECTS + REPLACES/AMENDS/GUIDED_BY sai (nhan doi), ghi lai ung vien dich vao 1 file
rieng de nguoi dung tu xac dinh dich nao dung (khong doan), roi xuat lai 2 file
chinh (_da_khop.csv, _can_ra.xlsx) cho dung so."""
from __future__ import annotations
import csv
import sys
from pathlib import Path

sys.path.insert(0, "D:/Project/GenQuesAI")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient

HERE = Path(__file__).parent


def main() -> None:
    s = get_settings()
    s_local = s.model_copy(update={
        "neo4j_uri": "bolt://localhost:7687", "neo4j_user": "neo4j",
        "neo4j_password": "123qwe", "neo4j_database": "neo4j",
    })
    neo = Neo4jClient(s_local)
    neo.verify()

    rows = neo.run("""
        MATCH (a:Action)-[:ENACTED_BY]->(src:Norm)
        WITH a, src, count{(a)-[:AFFECTS]->()} AS n_tgt
        WHERE n_tgt > 1
        MATCH (a)-[:AFFECTS]->(tgt:Norm)
        RETURN a.action_id AS action_id, src.so_hieu AS sh_nguon, src.tieu_de AS td_nguon,
               a.loai AS loai, tgt.norm_id AS tgt_norm_id, tgt.so_hieu AS sh_dich,
               tgt.tieu_de AS td_dich, tgt.ngay_ban_hanh AS ngay_dich
        ORDER BY a.action_id, tgt.norm_id
    """)
    print(f"Số dòng (Action x ứng viên đích) trước khi dọn: {len(rows):,}")

    out_path = HERE / "_dich_mo_ho.csv"
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["action_id", "VB nguồn", "Tên VB nguồn", "Loại cạnh", "so_hieu đích (trùng)",
                   "norm_id ứng viên", "Tên VB ứng viên", "Ngày ban hành ứng viên"])
        for r in rows:
            w.writerow([r["action_id"], r["sh_nguon"], r["td_nguon"], r["loai"], r["sh_dich"],
                       r["tgt_norm_id"], r["td_dich"], r["ngay_dich"]])
    n_action = len({r["action_id"] for r in rows})
    print(f"Đã ghi {n_action:,} Action mơ hồ ({len(rows):,} ứng viên) -> {out_path}")

    # Xoá cạnh sai (AFFECTS + REPLACES/AMENDS/GUIDED_BY tương ứng), đánh dấu Action
    # là "đích mơ hồ" — không tự đoán, không tự động duyệt.
    neo.run("""
        MATCH (a:Action)-[:ENACTED_BY]->(src:Norm)
        WITH a, src, count{(a)-[:AFFECTS]->()} AS n_tgt
        WHERE n_tgt > 1
        MATCH (a)-[r:AFFECTS]->(tgt:Norm)
        OPTIONAL MATCH (src)-[r2:REPLACES]->(tgt)
        OPTIONAL MATCH (src)-[r3:AMENDS]->(tgt)
        OPTIONAL MATCH (src)-[r4:GUIDED_BY]->(tgt)
        DELETE r, r2, r3, r4
        SET a.da_duyet = false, a.mismatch = false, a.only_llm = false, a.dich_mo_ho = true
    """)
    con_lai = neo.run("""
        MATCH (a:Action)-[:ENACTED_BY]->(src:Norm)
        WITH a, count{(a)-[:AFFECTS]->()} AS n_tgt
        WHERE n_tgt > 1
        RETURN count(a) AS n
    """)[0]["n"]
    print(f"Sau khi dọn: Action còn nhiều đích = {con_lai} (kỳ vọng 0)")

    tong = neo.run("MATCH (a:Action)-[:AFFECTS]->() RETURN count(*) AS n")[0]["n"]
    print(f"Tổng cạnh AFFECTS sau khi dọn: {tong:,}")


if __name__ == "__main__":
    main()
