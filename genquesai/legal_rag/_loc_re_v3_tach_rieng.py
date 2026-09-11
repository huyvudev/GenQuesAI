"""Lọc lại, tách RIÊNG tín hiệu từ "Căn cứ" và "Điều khoản thi hành" — để xem cái nào
đáng tin hơn (giả thuyết: Căn cứ chỉ là cơ sở pháp lý, không phải tuyên bố thay thế/sửa
đổi, nên đưa vào cùng dễ gây nhiễu).

Chạy: cd genquesai/legal_rag && python _loc_re_v3_tach_rieng.py
"""
from __future__ import annotations
import json
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")
sys.path.insert(0, ".")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient
from _ngu_canh_gon import lay_can_cu, lay_dieu_khoan_thi_hanh


def _chuan_hoa(s: str) -> str:
    return re.sub(r"\s+", "", (s or "")).upper()


def main() -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    with open("_loc_re_ket_qua_v2.jsonl", encoding="utf-8") as f:
        records = [json.loads(l) for l in f]
    print(f"Tổng {len(records)} bản ghi cần tách lại")

    cache_can_cu: dict[str, str] = {}
    cache_thi_hanh: dict[str, str] = {}
    ket_qua = []
    for i, r in enumerate(records):
        nid = r["norm_id"]
        if nid not in cache_can_cu:
            cache_can_cu[nid] = _chuan_hoa(lay_can_cu(nid))
        if nid not in cache_thi_hanh:
            cache_thi_hanh[nid] = _chuan_hoa(lay_dieu_khoan_thi_hanh(neo, nid))
        tsh = _chuan_hoa(r["target_so_hieu"])
        found_can_cu = bool(tsh) and tsh in cache_can_cu[nid]
        found_thi_hanh = bool(tsh) and tsh in cache_thi_hanh[nid]
        ket_qua.append({**r, "found_can_cu": found_can_cu, "found_thi_hanh": found_thi_hanh})
        if (i + 1) % 2000 == 0:
            print(f"  {i+1}/{len(records)}")

    with open("_loc_re_ket_qua_v3.jsonl", "w", encoding="utf-8") as f:
        for r in ket_qua:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print("\n== KẾT QUẢ THEO NHÓM ==")
    for nhom in ["A", "B", "C"]:
        sub = [r for r in ket_qua if r["nhom"] == nhom]
        tong = len(sub)
        chi_can_cu = sum(1 for r in sub if r["found_can_cu"] and not r["found_thi_hanh"])
        chi_thi_hanh = sum(1 for r in sub if r["found_thi_hanh"] and not r["found_can_cu"])
        ca_2 = sum(1 for r in sub if r["found_can_cu"] and r["found_thi_hanh"])
        khong_gi = sum(1 for r in sub if not r["found_can_cu"] and not r["found_thi_hanh"])
        chi_thi_hanh_tong = sum(1 for r in sub if r["found_thi_hanh"])
        print(f"  Nhóm {nhom} (tổng {tong}):")
        print(f"    Chỉ tìm thấy ở Căn cứ (nghi ngờ NHIỄU): {chi_can_cu}")
        print(f"    Chỉ tìm thấy ở Điều khoản thi hành: {chi_thi_hanh}")
        print(f"    Tìm thấy ở CẢ 2: {ca_2}")
        print(f"    Không tìm thấy ở đâu cả: {khong_gi}")
        print(f"    -> NẾU CHỈ DÙNG Điều khoản thi hành làm tín hiệu: found={chi_thi_hanh_tong} "
             f"({100*chi_thi_hanh_tong/tong:.1f}%), not_found={tong-chi_thi_hanh_tong} ({100*(tong-chi_thi_hanh_tong)/tong:.1f}%)")


if __name__ == "__main__":
    main()
