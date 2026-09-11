"""Lấy mẫu ngẫu nhiên từ backup của TỪNG NHÓM rủi ro đã áp dụng trong đợt rà soát, dùng
TOÀN VĂN NGUỒN ĐÚNG (đã sửa bug) để đo lại tỷ lệ sai thật — so sánh xem quyết định ĐÃ ÁP
DỤNG (revoke/relabel) có đúng không khi đọc đủ bằng chứng.

4 nhóm theo mức rủi ro đã phân tích:
  A. dong_thuan_cao — chưa từng đọc tay kiểm tra (16.671 cạnh)
  B. A1_trust — "tin Gemini KhongLienQuan" dựa trên "không tìm thấy" (~2.322 cạnh)
  C. A2_trust — "tin DeepSeek KhongLienQuan" dựa trên "không tìm thấy" (~656 cạnh)
  D. rule_tu_khoa — dựa trên đọc toàn văn tìm từ khóa (438 cạnh)

Chạy: cd genquesai/legal_rag && python _mau_do_lai_sai_that.py [so_luong_moi_nhom]
"""
from __future__ import annotations
import json
import random
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")
sys.path.insert(0, ".")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient
from _toan_van_dung import lay_toan_van_dung

_Q_TARGET_META_BY_SO_HIEU = "MATCH (n:Norm {so_hieu:$sh}) RETURN n.tieu_de AS tieu_de, n.loai_vb AS loai_vb LIMIT 1"
_Q_ACTION_INFO = """
MATCH (a:Action {action_id:$aid})-[:ENACTED_BY]->(src:Norm)
MATCH (a)-[:AFFECTS]->(tgt)
OPTIONAL MATCH (tgt)<-[:HAS_PART*0..]-(pn:Norm) WHERE 'Component' IN labels(tgt)
WITH src, coalesce(CASE WHEN 'Norm' IN labels(tgt) THEN tgt ELSE null END, pn) AS tgt_norm
RETURN src.norm_id AS norm_id, src.so_hieu AS so_hieu_nguon, tgt_norm.so_hieu AS target_so_hieu,
       tgt_norm.tieu_de AS tgt_tieu_de, tgt_norm.loai_vb AS tgt_loai_vb
"""

NHOM_FILES = {
    "A_dong_thuan_cao": ["_backup_dong_thuan_2llm_20260908_221048.jsonl"],
    "B_A1_trust": ["_backup_bat_dong_gemini_dung_20260909_070701.jsonl", "_backup_mong_found_20260910_101829.jsonl"],
    "C_A2_trust": ["_backup_bat_dong_A2_tin_deepseek_20260909_131530.jsonl"],
    "D_rule_tu_khoa": ["_backup_rule_tu_khoa_20260909_135716.jsonl"],
}


def doc_backup(paths: list[str]) -> list[dict]:
    out = []
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    out.append(json.loads(line))
        except FileNotFoundError:
            print(f"  CANH BAO: khong thay {p}")
    return out


def main(so_luong: int = 30) -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    random.seed(123)
    for ten_nhom, paths in NHOM_FILES.items():
        print(f"== Nhóm {ten_nhom} ==")
        records = doc_backup(paths)
        print(f"  {len(records)} bản ghi trong backup")
        if not records:
            continue
        mau = random.sample(records, min(so_luong, len(records)))
        out_path = f"_mau_dolai_{ten_nhom}.md"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# Đo lại sai thật — nhóm {ten_nhom} ({len(mau)} ca)\n\n")
            f.write("Mỗi ca đã bị SỬA trong đợt rà soát (xem 'Loại ĐÃ ÁP DỤNG'). Đọc TOÀN VĂN NGUỒN "
                   "ĐÚNG (đã sửa bug, đầy đủ Khoản/Điểm) bên dưới, tự phán quyết XEM QUYẾT ĐỊNH ĐÃ ÁP "
                   "DỤNG CÓ ĐÚNG KHÔNG dựa trên bằng chứng đầy đủ.\n\n---\n\n")
            for i, r in enumerate(mau, 1):
                nid = r.get("norm_id")
                tgt_meta = None
                tsh = r.get("target_so_hieu")
                so_hieu_nguon = r.get("so_hieu_nguon")
                if not nid:
                    info = neo.run(_Q_ACTION_INFO, aid=r["action_id"])
                    if not info:
                        continue
                    info = info[0]
                    nid = info["norm_id"]
                    so_hieu_nguon = info["so_hieu_nguon"]
                    tsh = info["target_so_hieu"]
                    tgt_meta = {"tieu_de": info["tgt_tieu_de"], "loai_vb": info["tgt_loai_vb"]}
                if not nid:
                    continue
                toan_van = lay_toan_van_dung(neo, nid)
                if tgt_meta is None and tsh:
                    tm = neo.run(_Q_TARGET_META_BY_SO_HIEU, sh=tsh)
                    if tm:
                        tgt_meta = tm[0]

                loai_ap_dung = r.get("loai_dung") or r.get("loai_moi_de_xuat") or "KhongLienQuan (revoke)"
                f.write(f"## Ca {i}/{len(mau)} — action_id={r.get('action_id')}\n\n")
                f.write(f"**Nguồn**: {so_hieu_nguon or nid}\n")
                f.write(f"**Đích (số hiệu)**: {tsh}")
                if tgt_meta:
                    f.write(f" — {tgt_meta['tieu_de']} ({tgt_meta['loai_vb']})\n")
                else:
                    f.write("\n")
                f.write(f"\n**Loại TRƯỚC KHI SỬA (đã có sẵn trong graph)**: {r.get('loai_hien_tai_graph')}\n")
                f.write(f"**Loại ĐÃ ÁP DỤNG trong đợt rà soát này**: {loai_ap_dung}\n")
                f.write(f"**DeepSeek đề xuất lúc đó**: {r.get('loai_deepseek')} — lý do: {r.get('ly_do_deepseek','')}\n")
                f.write(f"**Gemini đề xuất lúc đó**: {r.get('loai_gemini')} — lý do: {r.get('ly_do_gemini','')}\n")
                f.write(f"\n<details><summary>TOÀN VĂN NGUỒN ĐÚNG ({len(toan_van)} ký tự)</summary>\n\n```\n{toan_van[:20000]}\n```\n\n</details>\n\n")
                f.write("**VERDICT (quyết định đã áp dụng ĐÚNG hay SAI, nếu sai thì đúng ra là loại gì)**: \n\n---\n\n")
                if i % 10 == 0:
                    print(f"  {i}/{len(mau)}")
        print(f"  Đã ghi {out_path}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    main(n)
