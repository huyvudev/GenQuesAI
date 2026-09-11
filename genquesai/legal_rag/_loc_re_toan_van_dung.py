"""Lọc rẻ toàn bộ 4 nhóm rủi ro bằng TOÀN VĂN NGUỒN ĐÚNG (đã sửa bug thiếu 84% nội dung)
— kiểm tra xem số hiệu đích có xuất hiện ở BẤT KỲ ĐÂU trong toàn văn đầy đủ không.

Áp dụng cho các cạnh mà quyết định ĐÃ SỬA dựa trên "tin bên nói KhongLienQuan":
  - Nhóm A (đồng thuận cao): CHỈ phần 2 model đồng thuận KhongLienQuan (12.765/16.671).
  - Nhóm B (A1 trust — tin Gemini KhongLienQuan): toàn bộ 2.322.
  - Nhóm C (A2 trust — tin DeepSeek KhongLienQuan): toàn bộ 656.

KHÔNG áp dụng cho: phần đồng thuận cao về 1 LOẠI THẬT cụ thể (~3.906, không phải
KhongLienQuan) và rule_tu_khoa (438, đã đo rủi ro thấp 7% riêng) — xử lý khác sau.

Kết quả: "found" (nghi ngờ, cần xử lý riêng) vs "not_found" (tin cậy cao, để nguyên).

Chạy: cd genquesai/legal_rag && python _loc_re_toan_van_dung.py
"""
from __future__ import annotations
import json
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")
sys.path.insert(0, ".")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient
from _ngu_canh_gon import lay_ngu_canh_gon as lay_toan_van_dung

_Q_ACTION_INFO = """
MATCH (a:Action {action_id:$aid})-[:ENACTED_BY]->(src:Norm)
MATCH (a)-[:AFFECTS]->(tgt)
OPTIONAL MATCH (tgt)<-[:HAS_PART*0..]-(pn:Norm) WHERE 'Component' IN labels(tgt)
WITH src, coalesce(CASE WHEN 'Norm' IN labels(tgt) THEN tgt ELSE null END, pn) AS tgt_norm
RETURN src.norm_id AS norm_id, tgt_norm.so_hieu AS target_so_hieu
"""


def _chuan_hoa(s: str) -> str:
    return re.sub(r"\s+", "", (s or "")).upper()


def main() -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    ung_vien = []  # list of (nhom, action_id, norm_id, target_so_hieu)

    print("== Nhóm A (đồng thuận cao, chỉ phần KhongLienQuan) ==")
    with open("_backup_dong_thuan_2llm_20260908_221048.jsonl", encoding="utf-8") as f:
        a_khongLQ = [json.loads(l) for l in f if json.loads(l)["loai_moi_de_xuat"] == "KhongLienQuan"]
    print(f"  {len(a_khongLQ)} cạnh")
    for i, r in enumerate(a_khongLQ):
        info = neo.run(_Q_ACTION_INFO, aid=r["action_id"])
        if info and info[0]["norm_id"]:
            ung_vien.append(("A", r["action_id"], info[0]["norm_id"], info[0]["target_so_hieu"]))
        if (i + 1) % 2000 == 0:
            print(f"    {i+1}/{len(a_khongLQ)} tra cuu xong")

    print("== Nhóm B (A1 trust) ==")
    for p in ["_backup_bat_dong_gemini_dung_20260909_070701.jsonl", "_backup_mong_found_20260910_101829.jsonl"]:
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    r = json.loads(line)
                    if "loai_dung" in r:
                        continue  # day la ca sua loai, khong phai revoke KhongLienQuan
                    nid = r.get("norm_id")
                    tsh = r.get("target_so_hieu")
                    if nid and tsh:
                        ung_vien.append(("B", r["action_id"], nid, tsh))
        except FileNotFoundError:
            pass
    print(f"  {sum(1 for x in ung_vien if x[0]=='B')} cạnh")

    print("== Nhóm C (A2 trust) ==")
    with open("_backup_bat_dong_A2_tin_deepseek_20260909_131530.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            nid = r.get("norm_id")
            tsh = r.get("target_so_hieu")
            if nid and tsh:
                ung_vien.append(("C", r["action_id"], nid, tsh))
    print(f"  {sum(1 for x in ung_vien if x[0]=='C')} cạnh")

    print(f"\nTổng ứng viên: {len(ung_vien)}")
    print("== Đang tra toàn văn đúng + kiểm tra so_hieu (cache theo norm_id) ==")

    cache_toan_van: dict[str, str] = {}
    ket_qua = []
    for i, (nhom, aid, nid, tsh) in enumerate(ung_vien):
        if nid not in cache_toan_van:
            cache_toan_van[nid] = _chuan_hoa(lay_toan_van_dung(neo, nid))
        found = bool(tsh) and _chuan_hoa(tsh) in cache_toan_van[nid]
        ket_qua.append({"nhom": nhom, "action_id": aid, "norm_id": nid, "target_so_hieu": tsh, "found": found})
        if (i + 1) % 1000 == 0:
            print(f"  {i+1}/{len(ung_vien)} đã kiểm tra")

    with open("_loc_re_ket_qua_v2.jsonl", "w", encoding="utf-8") as f:
        for r in ket_qua:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    from collections import Counter
    dem = Counter((r["nhom"], r["found"]) for r in ket_qua)
    print("\n== KẾT QUẢ ==")
    for nhom in ["A", "B", "C"]:
        found = dem.get((nhom, True), 0)
        not_found = dem.get((nhom, False), 0)
        tong = found + not_found
        print(f"  Nhóm {nhom}: tổng {tong} | KHÔNG tìm thấy (tin cậy, để nguyên): {not_found} "
             f"| CÓ tìm thấy (nghi ngờ, cần xử lý): {found}")
    tong_found = sum(1 for r in ket_qua if r["found"])
    print(f"\nTỔNG NGHI NGỜ CẦN XỬ LÝ RIÊNG: {tong_found}/{len(ket_qua)}")
    print("Đã ghi _loc_re_ket_qua_v2.jsonl")


if __name__ == "__main__":
    main()
